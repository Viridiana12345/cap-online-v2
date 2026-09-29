import json
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
        use_https = self.request.is_secure()
        domain_override = None
        if not settings.DEBUG:
            use_https = True
            domain_override = settings.RENDER_EXTERNAL_HOSTNAME or "cap-online.onrender.com"
        opts = {
            "use_https": use_https,
            "token_generator": self.token_generator,
            "from_email": self.from_email,
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "request": self.request,
            "html_email_template_name": self.html_email_template_name,
            "extra_email_context": self.extra_email_context,
        }
        if domain_override:
            opts["domain_override"] = domain_override
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
    rules = profile.availability.filter(active=True, weekday=start_at.weekday())
    if not rules.exists():
        return True
    local_start = timezone.localtime(start_at).time()
    local_end = timezone.localtime(end_at).time()
    return rules.filter(start_time__lte=local_start, end_time__gte=local_end).exists()


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
    else:
        ctx["patient_count"] = User.objects.filter(pk__in=care_patient_ids(request.user)).distinct().count()
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
def calendar_patient(request):
    form = AppointmentCreateForm()
    form.fields["doctor"].queryset = User.objects.filter(doctor_profile__activo=True, is_active=True, groups__name="Doctores").distinct()
    return render(request, "portal/calendar_patient.html", {
        "notifications_count": _notifications_count(request.user), "form": form,
        "appointments": Appointment.objects.filter(patient=request.user).select_related("doctor").order_by("-start_at"),
    })


@doctor_required
def calendar_doctor(request):
    return render(request, "portal/calendar_doctor.html", {
        "notifications_count": _notifications_count(request.user),
        "appointments": Appointment.objects.filter(doctor=request.user).select_related("patient").order_by("-start_at"),
        "availability": request.user.doctor_profile.availability.all(),
        "availability_form": DoctorAvailabilityForm(),
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
    elif _appointment_conflict(appt.doctor, appt.start_at, appt.end_at):
        messages.error(request, "Ese horario ya está ocupado.")
    elif not _fits_availability(appt.doctor, appt.start_at, appt.end_at):
        messages.error(request, "El horario está fuera de la disponibilidad del psicólogo.")
    else:
        appt.save()
        _notify(appt.doctor, "Nueva cita", f"{_display_name(request.user)} solicitó una cita.")
        messages.success(request, "Cita solicitada. Queda pendiente de aprobación.")
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
    appt.save(update_fields=["status"])
    label = dict(Appointment.STATUS).get(new_status, new_status)
    _notify(appt.patient, f"Cita {label.lower()}", f"Tu cita del {timezone.localtime(appt.start_at):%d/%m/%Y %H:%M} cambió a {label}.", "appointment_confirmed" if new_status == "approved" else "appointment_changed")
    return redirect("portal_calendar_doctor")


@portal_required
@require_POST
def appointment_cancel(request, appt_id):
    appt = get_object_or_404(_appointment_queryset(request.user), pk=appt_id)
    if appt.status in {"done", "cancelled", "rejected"}:
        messages.error(request, "Esta cita ya no puede cancelarse.")
        return redirect("portal_calendar")
    appt.status = "cancelled"
    appt.cancelled_at = timezone.now()
    appt.cancelled_by = request.user
    appt.cancellation_reason = (request.POST.get("reason") or "Cancelada por el usuario")[:1000]
    appt.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason"])
    other = appt.doctor if request.user.id == appt.patient_id else appt.patient
    _notify(other, "Cita cancelada", f"La cita del {timezone.localtime(appt.start_at):%d/%m/%Y %H:%M} fue cancelada.", "appointment_cancelled")
    messages.success(request, "Cita cancelada.")
    return redirect("portal_calendar")


@patient_required
@require_POST
@transaction.atomic
def appointment_reschedule(request, appt_id):
    old = get_object_or_404(Appointment.objects.select_for_update(), pk=appt_id, patient=request.user)
    if old.status not in {"pending", "approved"}:
        messages.error(request, "Esta cita no puede reprogramarse.")
        return redirect("portal_calendar_patient")
    try:
        start_at = datetime.fromisoformat(request.POST.get("start_at"))
        end_at = datetime.fromisoformat(request.POST.get("end_at"))
        if timezone.is_naive(start_at): start_at = timezone.make_aware(start_at)
        if timezone.is_naive(end_at): end_at = timezone.make_aware(end_at)
    except Exception:
        messages.error(request, "Fecha u hora inválida.")
        return redirect("portal_calendar_patient")
    if start_at <= timezone.now() or end_at <= start_at or _appointment_conflict(old.doctor, start_at, end_at, exclude_id=old.id):
        messages.error(request, "El nuevo horario no está disponible.")
        return redirect("portal_calendar_patient")
    new = Appointment.objects.create(
        patient=old.patient, doctor=old.doctor, start_at=start_at, end_at=end_at,
        notes=old.notes, modalidad=old.modalidad, status="pending", rescheduled_from=old,
    )
    old.status = "rescheduled"
    old.save(update_fields=["status"])
    _notify(old.doctor, "Cita reprogramada", f"{_display_name(request.user)} propuso un nuevo horario.", "appointment_changed")
    messages.success(request, "Nuevo horario enviado para aprobación.")
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
        messages.error(request, "Revisa el horario de disponibilidad.")
    return redirect("portal_calendar_doctor")


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
    return JsonResponse({"ok": True, "id": msg.id})


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
        with transaction.atomic():
            user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"], first_name=d["first_name"], last_name=d["last_name"])
            user.groups.add(_ensure_group("Doctores"))
            DoctorProfile.objects.create(
                user=user, especialidad=d["especialidad"], cedula=d["cedula"], biografia=d["biografia"],
                experiencia_anios=d.get("experiencia_anios") or 0, telefono=d.get("telefono") or "",
                modalidad=d.get("modalidad") or "online", idiomas=d.get("idiomas") or "",
                costo_consulta=d.get("costo_consulta"), foto=d.get("foto"), activo=bool(d.get("activo")),
            )
        messages.success(request, "Psicólogo registrado.")
        return redirect("doctor_list")
    return render(request, "portal/rh/doctor_create.html", {"form": form})


@doctor_required
def mis_notas_clinicas(request):
    patients = User.objects.filter(pk__in=care_patient_ids(request.user), groups__name="Pacientes").distinct()
    notes = SessionNote.objects.filter(doctor=request.user, patient__in=patients).select_related("patient").order_by("-created_at")
    return render(request, "portal/mis_notas_clinicas.html", {"notas": notes, "paciente": None, "patients": patients, "notifications_count": _notifications_count(request.user)})


@doctor_required
def notas_paciente(request, patient_id):
    patient = get_object_or_404(User, pk=patient_id)
    if not has_care_relationship(request.user, patient): raise PermissionDenied
    notes = SessionNote.objects.filter(doctor=request.user, patient=patient).order_by("-created_at")
    if request.method == "POST":
        title = (request.POST.get("titulo") or "").strip()
        observations = (request.POST.get("observaciones") or "").strip()
        if not title or not observations: return HttpResponseBadRequest("Título y observaciones son obligatorios.")
        SessionNote.objects.create(
            doctor=request.user, patient=patient, titulo=title,
            estado_emocional=(request.POST.get("estado_emocional") or "")[:120],
            observaciones=observations, recomendaciones=request.POST.get("recomendaciones", ""),
        )
        registrar_auditoria(request, "Creó una nota clínica", "Notas clínicas")
        messages.success(request, "Nota clínica guardada.")
        return redirect("notas_paciente", patient_id=patient.id)
    return render(request, "portal/mis_notas_clinicas.html", {"paciente": patient, "notas": notes, "notifications_count": _notifications_count(request.user)})


def _video_appointment(user, appointment_id):
    appt = get_object_or_404(Appointment.objects.select_related("patient", "doctor"), pk=appointment_id)
    if user.id not in {appt.patient_id, appt.doctor_id}: raise PermissionDenied
    if appt.status != "approved" or appt.modalidad != "online": raise PermissionDenied
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
def video_room(request, appointment_id):
    appt = _video_appointment(request.user, appointment_id)
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
    ice_servers = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
    if settings.WEBRTC_TURN_URL:
        turn = {"urls": settings.WEBRTC_TURN_URL}
        if settings.WEBRTC_TURN_USERNAME:
            turn["username"] = settings.WEBRTC_TURN_USERNAME
        if settings.WEBRTC_TURN_CREDENTIAL:
            turn["credential"] = settings.WEBRTC_TURN_CREDENTIAL
        ice_servers.append(turn)
    return render(request, "portal/call_room.html", {
        "appointment": appt, "video_call": call, "room_key": room_key,
        "ice_servers": ice_servers, "is_initiator": is_initiator,
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
def call_signals_pull(request, room_key):
    _appointment_from_room(request.user, room_key)
    try: after = int(request.GET.get("after", "0"))
    except ValueError: after = 0
    qs = CallSignal.objects.filter(room_key=room_key).exclude(sender=request.user).filter(pk__gt=after)[:100]
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
