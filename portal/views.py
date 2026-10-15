from django.views.decorators.cache import never_cache
import json
import logging
from datetime import datetime, timedelta

from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import (
    AppointmentCreateForm, DoctorAvailabilityForm, DoctorCreateForm,
    DoctorProfileUpdateForm, PatientProfileUpdateForm, PatientRegistrationForm,
    UnambiguousPasswordResetForm,
)
from .models import (
    Appointment, AuditLog, CallSignal, ChatMessage, Conversation, DoctorAvailability,
    DoctorProfile, Notification, PatientProfile, SessionNote, VideoCall,
)
from .permissions import (
    admin_required, care_patient_ids, chat_contacts, chat_pair, doctor_required,
    has_care_relationship, is_admin, is_doctor, is_patient, patient_required,
    portal_required, role_required, thread_messages, visible_messages,
)

logger = logging.getLogger("portal")


class LoggingPasswordResetView(auth_views.PasswordResetView):
    form_class = UnambiguousPasswordResetForm

    def form_valid(self, form):
        email = form.cleaned_data.get("email")
        logger.info("Password reset requested for %s", email)
        opts = {
            "use_https": self.request.is_secure() or not settings.DEBUG,
            "token_generator": self.token_generator,
            "from_email": self.from_email,
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "request": self.request,
            "html_email_template_name": self.html_email_template_name,
            "extra_email_context": self.extra_email_context,
        }
        try:
            form.save(**opts)
        except Exception:
            logger.exception("Password reset email delivery failed")
            return render(self.request, self.template_name, {
                "form": form,
                "email_error": "No pudimos enviar el correo. Intenta nuevamente.",
            }, status=503)
        return super(auth_views.PasswordResetView, self).form_valid(form)


def _ensure_group(name):
    return Group.objects.get_or_create(name=name)[0]


def _dashboard_target(user):
    return "doctor_list" if is_admin(user) else "portal_dashboard"


def _display_name(user):
    return user.get_full_name() or user.email or user.username


def _notify(user, title, message, kind="appointment_changed"):
    return Notification.objects.create(user=user, title=title, message=message, notification_type=kind)


def _notifications_count(user):
    return Notification.objects.filter(user=user, is_read=False).count() + visible_messages(user).filter(is_read=False).count()


def _appointment_queryset(user):
    if is_doctor(user):
        return Appointment.objects.filter(doctor=user)
    if is_patient(user):
        return Appointment.objects.filter(patient=user)
    return Appointment.objects.none()


def _appointment_conflict(doctor, start_at, end_at, exclude_id=None):
    qs = Appointment.objects.filter(
        doctor=doctor, status__in=("pending", "approved"),
        start_at__lt=end_at, end_at__gt=start_at,
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def _fits_availability(doctor, start_at, end_at):
    profile = getattr(doctor, "doctor_profile", None)
    if not profile:
        return False
    local_start, local_end = timezone.localtime(start_at), timezone.localtime(end_at)
    if end_at - start_at != timedelta(minutes=30) or local_start.date() != local_end.date():
        return False
    if local_start.hour > 21 or (local_start.hour == 21 and local_start.minute > 0):
        return False
    if local_start.minute not in (0, 30) or local_start.second or local_start.microsecond:
        return False
    return profile.availability.filter(active=True, weekday=local_start.weekday(),
        start_time__lte=local_start.time(), end_time__gte=local_end.time()).exists()



def landing(request):
    doctors = DoctorProfile.objects.filter(activo=True, user__is_active=True).select_related("user")[:6]
    return render(request, "index.html", {"doctores": doctors})


def _login_account_for_email(email):
    """Resuelve cuentas actuales aunque existan duplicados historicos."""
    matches = User.objects.filter(email__iexact=email, is_active=True)
    if matches.count() == 1:
        return matches.first()
    exact_username = matches.filter(username__iexact=email)
    if exact_username.count() == 1:
        return exact_username.first()
    return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_target(request.user))
    context = {"email": "", "field_errors": {}}
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        context["email"] = email
        if not email:
            context["field_errors"]["email"] = "Ingresa tu correo."
        else:
            try:
                validate_email(email)
            except ValidationError:
                context["field_errors"]["email"] = "Correo no válido."
        if not password:
            context["field_errors"]["password"] = "Ingresa tu contraseña."
        if context["field_errors"]:
            return render(request, "auth/login.html", context)
        account = _login_account_for_email(email)
        user = authenticate(request, username=account.username, password=password) if account else None
        if user is None:
            context["login_error"] = "Correo o contraseña incorrectos."
            return render(request, "auth/login.html", context)
        if not (is_patient(user) or is_doctor(user) or is_admin(user)):
            context["login_error"] = "Acceso no habilitado. Contacta a administración."
            return render(request, "auth/login.html", context)
        login(request, user)
        messages.success(request, "Sesión iniciada correctamente.")
        return redirect(_dashboard_target(user))
    return render(request, "auth/login.html", context)


def signup(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_target(request.user))
    form = PatientRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        parts = data["full_name"].split(maxsplit=1)
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=data["email"], email=data["email"], password=data["password"],
                    first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
                )
                user.groups.add(_ensure_group("Pacientes"))
                PatientProfile.objects.create(user=user, telefono=data["telefono"], biografia=data["biografia"])
        except IntegrityError:
            form.add_error("email", "No pudimos registrar este correo. Usa otro o, si ya tienes cuenta, inicia sesión o recupera tu contraseña.")
        else:
            messages.success(request, "Cuenta creada. Ya puedes iniciar sesión.")
            return redirect("login")
    return render(request, "auth/register.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.success(request, "Sesión cerrada.")
    return redirect("login")


@role_required(is_patient, is_doctor, is_admin)
def dashboard(request):
    if is_admin(request.user):
        return redirect("doctor_list")
    now = timezone.now()
    qs = _appointment_queryset(request.user).select_related("doctor", "patient")
    next_appt = qs.filter(start_at__gte=now, status__in=("pending", "approved")).order_by("start_at").first()
    recent_appts = qs.order_by("-start_at")[:5]
    ctx = {
        "notifications_count": _notifications_count(request.user),
        "is_doctor": is_doctor(request.user),
        "next_appointment": next_appt,
        "recent_appointments": recent_appts,
        "unread_messages_count": visible_messages(request.user).filter(is_read=False).count(),
    }
    if is_patient(request.user):
        ctx["featured_doctors"] = DoctorProfile.objects.filter(activo=True, user__is_active=True).select_related("user")[:4]
        ctx["patient_stats"] = qs.aggregate(
            pending=Count("pk", filter=Q(status="pending")),
            approved=Count("pk", filter=Q(status="approved", end_at__gt=now)),
            completed=Count("pk", filter=Q(status="done")),
        )
        ctx["next_appointment"] = qs.filter(status__in=("pending", "approved"), end_at__gt=now).order_by("start_at").first()
        ctx["recent_appointments"] = qs.order_by("-start_at")[:4]
        ctx["now"] = now
        return render(request, "portal/dashboard_patient.html", ctx)
    else:
        ctx["patient_count"] = User.objects.filter(pk__in=care_patient_ids(request.user)).distinct().count()
        today = timezone.localdate(now)
        day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        day_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), datetime.min.time()))
        ctx["doctor_stats"] = qs.aggregate(
            today=Count("pk", filter=Q(start_at__gte=day_start, start_at__lt=day_end, status="approved")),
            pending=Count("pk", filter=Q(status="pending")),
            completed=Count("pk", filter=Q(status="done")),
        )
        ctx["today"] = today
        from .dashboard_metrics import doctor_charts
        ctx["charts"] = doctor_charts(request.user, today)
        ctx["now"] = now
        ctx["upcoming_sessions"] = qs.filter(status="approved", end_at__gt=now).order_by("start_at")[:5]
        ctx["pending_requests"] = qs.filter(status="pending").order_by("start_at")[:3]
        return render(request, "portal/dashboard_doctor.html", ctx)
    return render(request, "portal/dashboard.html", ctx)


@portal_required
def notifications(request):
    if request.method == "POST":
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return redirect("portal_notifications")
    ctx = {
        "notifications_count": _notifications_count(request.user),
        "notifications": Notification.objects.filter(user=request.user)[:50],
        "unread_messages": visible_messages(request.user).filter(is_read=False).order_by("-created_at")[:10],
        "appointments": _appointment_queryset(request.user).order_by("-created_at")[:10],
        "is_doctor": is_doctor(request.user),
    }
    return render(request, "portal/notifications.html", ctx)


@portal_required
def specialists(request):
    q = (request.GET.get("q") or "").strip()
    modality = (request.GET.get("modalidad") or "").strip()
    qs = DoctorProfile.objects.filter(activo=True, user__is_active=True).select_related("user")
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(especialidad__icontains=q))
    if modality in {"online", "presencial", "ambos"}:
        qs = qs.filter(modalidad=modality)
    return render(request, "portal/specialists.html", {
        "notifications_count": _notifications_count(request.user), "doctores": qs,
        "q": q, "modalidad": modality,
    })


@portal_required
def profile(request, doctor_id):
    doctor = get_object_or_404(DoctorProfile.objects.select_related("user"), pk=doctor_id, activo=True)
    return render(request, "portal/profile.html", {
        "notifications_count": _notifications_count(request.user), "doctor": doctor,
        "availability": doctor.availability.filter(active=True),
    })


@portal_required
def calendar_view(request):
    return redirect("portal_calendar_doctor" if is_doctor(request.user) else "portal_calendar_patient")


@patient_required
@never_cache
def calendar_patient(request):
    form = AppointmentCreateForm()
    doctors = User.objects.filter(
        doctor_profile__activo=True, is_active=True, groups__name="Doctores",
    ).select_related("doctor_profile").distinct().order_by("first_name", "last_name")
    form.fields["doctor"].queryset = doctors
    status_filter = (request.GET.get("status") or "all").strip()
    appointments = Appointment.objects.filter(patient=request.user).select_related("doctor").order_by("-start_at")
    valid_statuses = {value for value, _ in Appointment.STATUS}
    if status_filter in valid_statuses:
        appointments = appointments.filter(status=status_filter)
    else:
        status_filter = "all"
    return render(request, "portal/calendar_patient_clean.html", {
        "notifications_count": _notifications_count(request.user), "form": form,
        "appointments": appointments, "status_filter": status_filter,
    })


@patient_required
@never_cache
def appointment_availability_api(request):
    import calendar
    try:
        doctor_id = int(request.GET.get("doctor", ""))
        monthly = bool(request.GET.get("month"))
        selected = datetime.strptime(request.GET.get("month") if monthly else request.GET.get("date", ""), "%Y-%m" if monthly else "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return JsonResponse({"error": "Selecciona un especialista y una fecha v\u00e1lida."}, status=400)
    doctor = get_object_or_404(User.objects.select_related("doctor_profile"), pk=doctor_id,
        is_active=True, doctor_profile__activo=True, groups__name="Doctores")
    days = [selected + timedelta(days=i) for i in range(calendar.monthrange(selected.year, selected.month)[1] if monthly else 1)]
    ranges = list(DoctorAvailability.objects.filter(doctor=doctor.doctor_profile, active=True).values_list("weekday", "start_time", "end_time"))
    begin = timezone.make_aware(datetime.combine(days[0], datetime.min.time()))
    finish = timezone.make_aware(datetime.combine(days[-1] + timedelta(days=1), datetime.min.time()))
    occupied = Appointment.objects.filter(doctor=doctor, status__in=("pending", "approved"), start_at__lt=finish, end_at__gt=begin)
    exclude = request.GET.get("exclude")
    if exclude:
        own = get_object_or_404(Appointment, pk=exclude, patient=request.user, doctor=doctor)
        occupied = occupied.exclude(pk=own.pk)
    occupied = list(occupied.values_list("start_at", "end_at"))
    now = timezone.now()
    result = {}
    for day in days:
        slots = {}
        for weekday, start, end in ranges:
            if weekday != day.weekday():
                continue
            minute = ((start.hour * 60 + start.minute + (1 if start.second else 0) + 29) // 30) * 30
            while minute <= 21 * 60 and minute + 30 <= end.hour * 60 + end.minute:
                cursor = timezone.make_aware(datetime.combine(day, datetime.min.time())) + timedelta(minutes=minute)
                stop = cursor + timedelta(minutes=30)
                if cursor > now and not any(cursor < busy_end and stop > busy_start for busy_start, busy_end in occupied):
                    slots[cursor.isoformat()] = {"start": cursor.isoformat(), "end": stop.isoformat(), "available": True, "state": "available"}
                minute += 30
        result[day.isoformat()] = sorted(slots.values(), key=lambda slot: slot["start"])
    if monthly:
        return JsonResponse({"days": result, "duration": 30, "availability_configured": bool(ranges)})
    return JsonResponse({"date": selected.isoformat(), "duration": 30, "slots": result[selected.isoformat()]})


@doctor_required
def calendar_doctor(request):
    return render(request, "portal/calendar_doctor.html", {
        "notifications_count": _notifications_count(request.user),
        "appointments": Appointment.objects.filter(doctor=request.user).select_related("patient").order_by("-start_at"),
        "availability": request.user.doctor_profile.availability.all(),
        "availability_form": DoctorAvailabilityForm(),
        "now": timezone.now(),
    })


@patient_required
@require_POST
def appointment_create(request):
    form = AppointmentCreateForm(request.POST)
    form.fields["doctor"].queryset = User.objects.filter(doctor_profile__activo=True, is_active=True, groups__name="Doctores").distinct()
    if not form.is_valid():
        messages.error(request, "Revisa los datos de la cita.")
        return redirect("portal_calendar_patient")
    appt = form.save(commit=False)
    appt.patient = request.user
    if appt.start_at <= timezone.now() or appt.end_at <= appt.start_at:
        messages.error(request, "Selecciona una fecha futura y un horario válido.")
    elif not _fits_availability(appt.doctor, appt.start_at, appt.end_at):
        messages.error(request, "El horario está fuera de la disponibilidad del psicólogo.")
    else:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=appt.doctor_id)
            if _appointment_conflict(appt.doctor, appt.start_at, appt.end_at):
                messages.error(request, "Este horario ya no está disponible. Selecciona otra fecha u hora.")
                return redirect("portal_calendar_patient")
            appt.save()
            _notify(appt.doctor, "Nueva cita", f"{_display_name(request.user)} solicitó una cita.")
        messages.success(request, "Cita solicitada correctamente. Queda pendiente de aprobación.")
    return redirect("portal_calendar_patient")


@doctor_required
@require_POST
@transaction.atomic
def appointment_update_status(request, appt_id, new_status):
    appt = get_object_or_404(Appointment.objects.select_for_update(), pk=appt_id, doctor=request.user)
    allowed = {"pending": {"approved", "rejected"}, "approved": {"done"}}
    if new_status not in allowed.get(appt.status, set()):
        return HttpResponseBadRequest("Transición no permitida.")
    appt.status = new_status
    update_fields = ["status"]
    if new_status == "rejected":
        reason = (request.POST.get("rejection_reason") or "").strip()
        if not reason:
            messages.error(request, "Indica el motivo del rechazo.")
            return redirect("portal_calendar_doctor")
        appt.cancellation_reason = reason[:1000]
        update_fields.append("cancellation_reason")
    appt.save(update_fields=update_fields)
    label = dict(Appointment.STATUS).get(new_status, new_status)
    detail = f" Motivo: {appt.cancellation_reason}" if new_status == "rejected" else ""
    _notify(appt.patient, f"Cita {label.lower()}", f"Tu cita del {timezone.localtime(appt.start_at):%d/%m/%Y %H:%M} cambió a {label}.{detail}", "appointment_confirmed" if new_status == "approved" else "appointment_changed")
    messages.success(request, "Estado de la cita actualizado correctamente.")
    return redirect("portal_calendar_doctor")


@portal_required
@require_POST
@transaction.atomic
def appointment_cancel(request, appt_id):
    appt = get_object_or_404(_appointment_queryset(request.user).select_for_update(), pk=appt_id)
    if appt.status in {"done", "cancelled", "rejected"}:
        messages.error(request, "Esta cita ya no puede cancelarse.")
        return redirect("portal_calendar")
    reason = (request.POST.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        messages.error(request, "Indica un motivo de cancelaci\u00f3n de hasta 1000 caracteres.")
        return redirect("portal_calendar")
    appt.status = "cancelled"
    appt.cancelled_at = timezone.now()
    appt.cancelled_by = request.user
    appt.cancellation_reason = reason
    appt.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason"])
    other = appt.doctor if request.user.id == appt.patient_id else appt.patient
    _notify(other, "Cita cancelada", f"La cita del {timezone.localtime(appt.start_at):%d/%m/%Y %H:%M} fue cancelada.", "appointment_cancelled")
    messages.success(request, "Cita cancelada correctamente.")
    return redirect("portal_calendar")


@patient_required
@require_POST
@transaction.atomic
def appointment_reschedule(request, appt_id):
    old = get_object_or_404(Appointment.objects.select_for_update(), pk=appt_id, patient=request.user)
    if old.status not in {"pending", "approved"}:
        messages.error(request, "Esta cita no puede reprogramarse.")
        return redirect("portal_calendar_patient")
    reason = (request.POST.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        messages.error(request, "Indica un motivo de modificaci\u00f3n de hasta 1000 caracteres.")
        return redirect("portal_calendar_patient")
    try:
        start_at = datetime.fromisoformat(request.POST.get("start_at"))
        end_at = datetime.fromisoformat(request.POST.get("end_at"))
        if timezone.is_naive(start_at): start_at = timezone.make_aware(start_at)
        if timezone.is_naive(end_at): end_at = timezone.make_aware(end_at)
    except Exception:
        messages.error(request, "Fecha u hora inválida.")
        return redirect("portal_calendar_patient")
    if start_at <= timezone.now() or end_at <= start_at or not _fits_availability(old.doctor, start_at, end_at):
        messages.error(request, "El nuevo horario no está disponible.")
        return redirect("portal_calendar_patient")
    User.objects.select_for_update().get(pk=old.doctor_id)
    if _appointment_conflict(old.doctor, start_at, end_at, exclude_id=old.id):
        messages.error(request, "Este horario ya no está disponible. Selecciona otra fecha u hora.")
        return redirect("portal_calendar_patient")
    previous = timezone.localtime(old.start_at).strftime("%d/%m/%Y %H:%M")
    old.start_at, old.end_at, old.status = start_at, end_at, "pending"
    old.save(update_fields=["start_at", "end_at", "status"])
    detail = f"Cita #{old.pk}: {previous} -> {timezone.localtime(start_at):%d/%m/%Y %H:%M}. Motivo: {reason}"
    _notify(old.doctor, "Cita modificada", detail, "appointment_changed")
    _notify(old.patient, "Cita modificada", detail, "appointment_changed")
    registrar_auditoria(request, f"Modific\u00f3 cita #{old.pk}", "Citas")
    messages.success(request, "Cita modificada correctamente. El nuevo horario queda pendiente de aprobaci\u00f3n.")
    return redirect("portal_calendar_patient")


@doctor_required
@require_POST
def availability_create(request):
    form = DoctorAvailabilityForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.doctor = request.user.doctor_profile
        obj.save()
        messages.success(request, "Disponibilidad agregada.")
    else:
        return render(request, "portal/availability_edit.html", {"form": form, "is_new": True})
    return redirect("portal_calendar_doctor")


@doctor_required
def availability_edit(request, availability_id):
    availability = get_object_or_404(DoctorAvailability, pk=availability_id, doctor=request.user.doctor_profile)
    form = DoctorAvailabilityForm(request.POST if request.method == "POST" else None, instance=availability)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Horario actualizado correctamente.")
        return redirect("portal_calendar_doctor")
    return render(request, "portal/availability_edit.html", {"form": form})


@doctor_required
@require_POST
def availability_delete(request, availability_id):
    get_object_or_404(DoctorAvailability, pk=availability_id, doctor=request.user.doctor_profile).delete()
    messages.success(request, "Horario eliminado.")
    return redirect("portal_calendar_doctor")


@portal_required
def chat(request, user_id=None):
    contacts = chat_contacts(request.user).order_by("first_name", "last_name", "username")
    receiver = None
    thread = []
    if user_id:
        receiver = get_object_or_404(contacts, pk=user_id)
        thread = thread_messages(request.user, receiver).order_by("created_at")
        thread.filter(receiver=request.user, is_read=False).update(is_read=True)
    return render(request, "portal/chat.html", {
        "notifications_count": _notifications_count(request.user), "users": contacts,
        "receiver": receiver, "thread": thread,
    })


@portal_required
@require_POST
def send_message(request, user_id):
    receiver = get_object_or_404(chat_contacts(request.user), pk=user_id)
    text = (request.POST.get("text") or "").strip()
    if text:
        _send_chat_message(request.user, receiver, text)
    return redirect("portal_chat_with", user_id=receiver.id)


@portal_required
def chat_thread_api(request, user_id):
    other = get_object_or_404(chat_contacts(request.user), pk=user_id)
    try: after_id = int(request.GET.get("after", "0"))
    except ValueError: after_id = 0
    qs = thread_messages(request.user, other).order_by("id")
    if after_id: qs = qs.filter(id__gt=after_id)
    items = [{"id": m.id, "sender_id": m.sender_id, "text": m.text, "created_at": m.created_at.isoformat()} for m in qs[:200]]
    thread_messages(request.user, other).filter(receiver=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"messages": items})


@portal_required
@require_POST
def chat_send_api(request, user_id):
    other = get_object_or_404(chat_contacts(request.user), pk=user_id)
    text = (request.POST.get("text") or "").strip()
    if not text: return HttpResponseBadRequest("missing text")
    msg = _send_chat_message(request.user, other, text)
    return JsonResponse({"ok": True, "id": msg.id, "message": {
        "id": msg.id, "sender_id": msg.sender_id, "text": msg.text,
        "created_at": msg.created_at.isoformat(),
    }})


@transaction.atomic
def _send_chat_message(sender, receiver, text):
    patient, doctor = chat_pair(sender, receiver)
    conversation, _ = Conversation.objects.get_or_create(patient=patient, doctor=doctor)
    msg = ChatMessage(conversation=conversation, sender=sender, receiver=receiver, text=text)
    msg.full_clean(); msg.save()
    _notify(receiver, "Nuevo mensaje", f"Tienes un mensaje de {_display_name(sender)}.", "new_message")
    return msg


@portal_required
@transaction.atomic
def settings_view(request):
    doc = is_doctor(request.user)
    profile = request.user.doctor_profile if doc else PatientProfile.objects.get_or_create(user=request.user)[0]
    form_cls = DoctorProfileUpdateForm if doc else PatientProfileUpdateForm
    form = form_cls(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        full_name = (request.POST.get("full_name") or "").strip().split(maxsplit=1)
        if full_name:
            request.user.first_name = full_name[0]
            request.user.last_name = full_name[1] if len(full_name) > 1 else ""
            request.user.save(update_fields=["first_name", "last_name"])
        form.save(); messages.success(request, "Perfil actualizado.")
        return redirect("portal_settings")
    return render(request, "portal/settings.html", {
        "notifications_count": _notifications_count(request.user), "is_doctor": doc,
        "form": form, "full_name": request.user.get_full_name(),
    })


@portal_required
@require_POST
def update_profile(request):
    return redirect("portal_settings")


@admin_required
def doctor_list(request):
    doctors = DoctorProfile.objects.select_related("user").order_by("user__first_name", "user__last_name")
    return render(request, "portal/rh/doctor_list.html", {
        "doctores": doctors,
        "doctor_total": doctors.count(),
        "doctor_active": doctors.filter(activo=True, user__is_active=True).count(),
        "doctor_inactive": doctors.filter(Q(activo=False) | Q(user__is_active=False)).distinct().count(),
    })


@admin_required
def doctor_create(request):
    form = DoctorCreateForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"], first_name=d["first_name"], last_name=d["last_name"])
                user.groups.add(_ensure_group("Doctores"))
                DoctorProfile.objects.create(
                    user=user, especialidad=d["especialidad"], cedula=d["cedula"], biografia=d["biografia"],
                    experiencia_anios=d.get("experiencia_anios") or 0, telefono=d.get("telefono") or "",
                    modalidad=d.get("modalidad") or "online", idiomas=d.get("idiomas") or "",
                    costo_consulta=d.get("costo_consulta"), foto=d.get("foto"), activo=bool(d.get("activo")),
                )
        except (CloudinaryError, ValueError):
            logger.exception("Cloudinary failed while creating a doctor profile")
            form.add_error(
                "foto",
                "No pudimos subir la fotografía. Revisa la configuración de Cloudinary e intenta nuevamente.",
            )
        else:
            messages.success(request, "Psicólogo registrado.")
            return redirect("doctor_list")
    return render(request, "portal/rh/doctor_create.html", {"form": form})


@doctor_required
def mis_notas_clinicas(request):
    own = SessionNote.objects.filter(doctor=request.user)
    patients = User.objects.filter(Q(pk__in=care_patient_ids(request.user)) | Q(pk__in=own.values("patient_id"))).distinct().order_by("first_name", "username")
    notes = own.select_related("patient", "appointment").order_by("-created_at", "-pk")
    search = request.GET.get("q", "").strip()[:150]
    if search:
        notes = notes.filter(Q(titulo__icontains=search) | Q(patient__first_name__icontains=search) | Q(patient__last_name__icontains=search) | Q(patient__username__icontains=search))
    from django.core.paginator import Paginator
    return render(request, "portal/mis_notas_clinicas.html", {"notas": Paginator(notes, 12).get_page(request.GET.get("page")), "patients": patients, "search": search, "notifications_count": _notifications_count(request.user)})


@doctor_required
def notas_paciente(request, patient_id):
    from .note_forms import SessionNoteForm
    from django.core.paginator import Paginator
    patient = get_object_or_404(User, pk=patient_id)
    notes = SessionNote.objects.filter(doctor=request.user, patient=patient).select_related("appointment").order_by("-created_at", "-pk")
    can_create = has_care_relationship(request.user, patient)
    if not can_create and not notes.exists():
        raise PermissionDenied
    if request.method == "POST" and not can_create:
        raise PermissionDenied
    form = SessionNoteForm(request.POST if request.method == "POST" else None, doctor=request.user, patient=patient)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            note = form.save(commit=False)
            note.doctor = request.user
            note.patient = patient
            note.save()
            registrar_auditoria(request, f"Creó nota clínica #{note.pk}", "Notas clínicas")
        messages.success(request, "Nota clínica guardada.")
        return redirect("notas_paciente", patient_id=patient.pk)
    return render(request, "portal/mis_notas_clinicas.html", {"paciente": patient, "notas": Paginator(notes, 12).get_page(request.GET.get("page")), "form": form, "can_create": can_create, "notifications_count": _notifications_count(request.user)})


@doctor_required
def note_edit(request, note_id):
    from .note_forms import SessionNoteForm
    note = get_object_or_404(SessionNote.objects.select_related("patient"), pk=note_id, doctor=request.user)
    form = SessionNoteForm(request.POST if request.method == "POST" else None, instance=note, doctor=request.user, patient=note.patient)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            registrar_auditoria(request, f"Editó nota clínica #{note.pk}", "Notas clínicas")
        messages.success(request, "Nota clínica actualizada correctamente.")
        return redirect("notas_paciente", patient_id=note.patient_id)
    return render(request, "portal/note_edit.html", {"form": form, "note": note})


@doctor_required
def note_delete(request, note_id):
    note = get_object_or_404(SessionNote.objects.select_related("patient"), pk=note_id, doctor=request.user)
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            return HttpResponseBadRequest("Confirma la eliminación de la nota.")
        with transaction.atomic():
            registrar_auditoria(request, f"Eliminó nota clínica #{note.pk}", "Notas clínicas")
            note.delete()
        messages.success(request, "Nota clínica eliminada correctamente.")
        return redirect("mis_notas_clinicas")
    return render(request, "portal/note_delete.html", {"note": note})


def _video_appointment(user, appointment_id):
    appt = get_object_or_404(Appointment.objects.select_related("patient", "doctor"), pk=appointment_id)
    if user.id not in {appt.patient_id, appt.doctor_id}: raise PermissionDenied
    if appt.status != "approved" or appt.modalidad != "online": raise PermissionDenied
    now = timezone.now()
    if now < appt.start_at or now > appt.end_at: raise PermissionDenied
    return appt


@portal_required
def video_calls(request):
    appointments = Appointment.objects.filter(
        status="approved", modalidad="online",
    ).select_related("patient", "doctor")
    if is_doctor(request.user):
        appointments = appointments.filter(doctor=request.user)
    else:
        appointments = appointments.filter(patient=request.user)
    return render(request, "portal/video_calls.html", {
        "appointments": appointments.order_by("start_at"),
        "notifications_count": _notifications_count(request.user),
        "now": timezone.now(),
    })


@portal_required
@never_cache
def video_room(request, appointment_id):
    appt = _video_appointment(request.user, appointment_id)
    from .webrtc import TurnUnavailable, rtc_configuration
    try:
        rtc_config = rtc_configuration(request.user.pk)
    except TurnUnavailable:
        return render(request, "portal/turn_unavailable.html", {"appointment": appt}, status=503)
    call, _ = VideoCall.objects.get_or_create(appointment=appt)
    room_key = f"cap-appointment-{appt.id}"
    is_initiator = request.user.id == appt.doctor_id
    stale = call.started_at and call.started_at < timezone.now() - timedelta(hours=6)
    if call.status in {"pending", "ended", "cancelled"} or stale:
        CallSignal.objects.filter(room_key=room_key).delete()
        call.started_at = timezone.now()
        call.ended_at = None
        call.status = "in_progress"
        call.save(update_fields=["started_at", "ended_at", "status"])
    # El doctor crea cada negociación. Al abrir o recargar su sala se eliminan
    # ofertas anteriores; el paciente anuncia periódicamente que está listo.
    if is_initiator:
        CallSignal.objects.filter(room_key=room_key).delete()
    return render(request, "portal/call_room.html", {
        "appointment": appt, "video_call": call, "room_key": room_key,
        "rtc_config": rtc_config, "is_initiator": is_initiator,
        "notifications_count": _notifications_count(request.user),
    })


@portal_required
@require_POST
def video_end(request, appointment_id):
    appt = _video_appointment(request.user, appointment_id)
    call = get_object_or_404(VideoCall, appointment=appt)
    call.status = "ended"; call.ended_at = timezone.now(); call.save(update_fields=["status", "ended_at"])
    CallSignal.objects.filter(room_key=f"cap-appointment-{appt.id}").delete()
    return redirect("portal_calendar")


def _appointment_from_room(user, room_key):
    prefix = "cap-appointment-"
    if not room_key.startswith(prefix): raise PermissionDenied
    try: appointment_id = int(room_key[len(prefix):])
    except ValueError: raise PermissionDenied
    return _video_appointment(user, appointment_id)


@portal_required
@never_cache
def call_signals_pull(request, room_key):
    _appointment_from_room(request.user, room_key)
    try: after = int(request.GET.get("after", "0"))
    except ValueError: after = 0
    qs = CallSignal.objects.filter(room_key=room_key).exclude(sender=request.user).filter(pk__gt=after).order_by("pk")[:100]
    return JsonResponse({"signals": [{"id": s.id, "sender_id": s.sender_id, "payload": s.payload} for s in qs]})


@portal_required
@require_POST
def call_signals_push(request, room_key):
    _appointment_from_room(request.user, room_key)
    try: payload = json.loads(request.body.decode("utf-8"))
    except Exception: return HttpResponseBadRequest("invalid json")
    s = CallSignal.objects.create(room_key=room_key, sender=request.user, payload=payload)
    return JsonResponse({"ok": True, "id": s.id})


def politica_privacidad(request):
    return render(request, "auth/politica_privacidad.html")


def registrar_auditoria(request, accion, modulo):
    AuditLog.objects.create(usuario=request.user if request.user.is_authenticated else None, accion=accion, modulo=modulo, ip=request.META.get("REMOTE_ADDR"))
