import hashlib
import json
import secrets
from datetime import datetime
from functools import wraps

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    Appointment, ChatMessage, Conversation, DoctorProfile, MobileToken,
    Notification, VideoCall,
)
from .permissions import is_admin, is_doctor, is_patient, chat_contacts, chat_pair, thread_messages


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _issue_token(user):
    raw = secrets.token_urlsafe(40)
    MobileToken.objects.create(user=user, token_hash=_hash_token(raw))
    return raw


def _role(user):
    if is_admin(user):
        return "admin"
    if is_doctor(user):
        return "doctor"
    if is_patient(user):
        return "patient"
    return "unknown"


def _serialize_user(user):
    data = {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name() or user.username,
        "role": _role(user),
    }
    if hasattr(user, "doctor_profile"):
        p = user.doctor_profile
        data["doctor_profile"] = {
            "id": p.id,
            "especialidad": p.especialidad,
            "cedula": p.cedula,
            "biografia": p.biografia,
            "experiencia_anios": p.experiencia_anios,
            "telefono": p.telefono,
            "modalidad": p.modalidad,
            "idiomas": p.idiomas,
            "costo_consulta": str(p.costo_consulta) if p.costo_consulta is not None else None,
            "foto": p.foto.url if p.foto else None,
        }
    return data


def bearer_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JsonResponse({"detail": "Token requerido."}, status=401)
        raw = header[7:].strip()
        try:
            token = MobileToken.objects.select_related("user").get(token_hash=_hash_token(raw), revoked=False)
        except MobileToken.DoesNotExist:
            return JsonResponse({"detail": "Token inválido o revocado."}, status=401)
        if not token.user.is_active:
            return JsonResponse({"detail": "Cuenta inactiva."}, status=403)
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        request.api_user = token.user
        request.api_token = token
        return view(request, *args, **kwargs)
    return wrapped


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def login_api(request):
    if request.method == "OPTIONS":
        return JsonResponse({})
    data = _json(request)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    try:
        account = User.objects.get(email__iexact=email)
    except (User.DoesNotExist, User.MultipleObjectsReturned):
        return JsonResponse({"detail": "Correo o contraseña incorrectos."}, status=400)
    user = authenticate(request, username=account.username, password=password)
    if not user or _role(user) == "unknown":
        return JsonResponse({"detail": "Correo o contraseña incorrectos."}, status=400)
    MobileToken.objects.filter(user=user, revoked=False).update(revoked=True)
    raw = _issue_token(user)
    return JsonResponse({"token": raw, "user": _serialize_user(user)})


@csrf_exempt
@bearer_required
@require_http_methods(["POST", "OPTIONS"])
def logout_api(request):
    request.api_token.revoked = True
    request.api_token.save(update_fields=["revoked"])
    return JsonResponse({"ok": True})


@bearer_required
@require_http_methods(["GET"])
def me_api(request):
    return JsonResponse({"user": _serialize_user(request.api_user)})


@bearer_required
@require_http_methods(["GET"])
def doctors_api(request):
    q = (request.GET.get("q") or "").strip()
    qs = DoctorProfile.objects.filter(activo=True, user__is_active=True).select_related("user")
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(especialidad__icontains=q))
    items = []
    for p in qs.order_by("user__first_name", "user__last_name"):
        items.append({
            "id": p.id,
            "user_id": p.user_id,
            "name": p.user.get_full_name() or p.user.username,
            "especialidad": p.especialidad,
            "biografia": p.biografia,
            "experiencia_anios": p.experiencia_anios,
            "modalidad": p.modalidad,
            "idiomas": p.idiomas,
            "costo_consulta": str(p.costo_consulta) if p.costo_consulta is not None else None,
            "foto": p.foto.url if p.foto else None,
        })
    return JsonResponse({"doctors": items})


def _appointment_dict(a, user):
    counterpart = a.doctor if a.patient_id == user.id else a.patient
    return {
        "id": a.id,
        "patient_id": a.patient_id,
        "doctor_id": a.doctor_id,
        "counterpart": counterpart.get_full_name() or counterpart.username,
        "start_at": a.start_at.isoformat(),
        "end_at": a.end_at.isoformat(),
        "notes": a.notes,
        "modalidad": a.modalidad,
        "status": a.status,
        "cancellation_reason": a.cancellation_reason,
        "video_available": bool(a.status == "approved" and a.modalidad == "online"),
    }


@csrf_exempt
@bearer_required
@require_http_methods(["GET", "POST", "OPTIONS"])
def appointments_api(request):
    user = request.api_user
    if request.method == "GET":
        qs = Appointment.objects.filter(doctor=user) if is_doctor(user) else Appointment.objects.filter(patient=user)
        return JsonResponse({"appointments": [_appointment_dict(a, user) for a in qs.select_related("doctor", "patient")[:100]]})
    if not is_patient(user):
        return JsonResponse({"detail": "Solo pacientes pueden crear citas."}, status=403)
    data = _json(request)
    try:
        doctor = User.objects.get(pk=int(data.get("doctor_id")), groups__name="Doctores", doctor_profile__activo=True)
        start_at = datetime.fromisoformat(data.get("start_at"))
        end_at = datetime.fromisoformat(data.get("end_at"))
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at)
        if timezone.is_naive(end_at):
            end_at = timezone.make_aware(end_at)
    except Exception:
        return JsonResponse({"detail": "Datos de cita inválidos."}, status=400)
    if start_at <= timezone.now() or end_at <= start_at:
        return JsonResponse({"detail": "Horario inválido."}, status=400)
    overlap = Appointment.objects.filter(doctor=doctor, status__in=["pending", "approved"], start_at__lt=end_at, end_at__gt=start_at).exists()
    if overlap:
        return JsonResponse({"detail": "El horario ya no está disponible."}, status=409)
    a = Appointment.objects.create(
        patient=user, doctor=doctor, start_at=start_at, end_at=end_at,
        notes=(data.get("notes") or "")[:255], modalidad=data.get("modalidad") if data.get("modalidad") in ["online", "presencial"] else "online",
    )
    Notification.objects.create(user=doctor, title="Nueva cita", message=f"{user.get_full_name() or user.username} solicitó una cita.", notification_type="appointment_changed")
    return JsonResponse({"appointment": _appointment_dict(a, user)}, status=201)


@csrf_exempt
@bearer_required
@require_http_methods(["POST", "OPTIONS"])
def appointment_cancel_api(request, appointment_id):
    user = request.api_user
    a = get_object_or_404(Appointment, pk=appointment_id)
    if user.id not in {a.patient_id, a.doctor_id}:
        return JsonResponse({"detail": "Sin permiso."}, status=403)
    if a.status in {"done", "cancelled", "rejected"}:
        return JsonResponse({"detail": "La cita ya no puede cancelarse."}, status=400)
    data = _json(request)
    a.status = "cancelled"
    a.cancelled_at = timezone.now()
    a.cancelled_by = user
    a.cancellation_reason = (data.get("reason") or "Cancelada por el usuario")[:1000]
    a.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason"])
    other = a.doctor if user.id == a.patient_id else a.patient
    Notification.objects.create(user=other, title="Cita cancelada", message=f"La cita del {a.start_at:%d/%m/%Y %H:%M} fue cancelada.", notification_type="appointment_cancelled")
    return JsonResponse({"ok": True})


@bearer_required
@require_http_methods(["GET"])
def conversations_api(request):
    user = request.api_user
    contacts = chat_contacts(user).order_by("first_name", "last_name")
    return JsonResponse({"contacts": [{"id": u.id, "name": u.get_full_name() or u.username, "role": _role(u)} for u in contacts]})


@csrf_exempt
@bearer_required
@require_http_methods(["GET", "POST", "OPTIONS"])
def messages_api(request, other_id):
    user = request.api_user
    try:
        other = chat_contacts(user).get(pk=other_id)
    except User.DoesNotExist:
        return JsonResponse({"detail": "Conversación no autorizada."}, status=403)
    if request.method == "GET":
        qs = thread_messages(user, other).order_by("created_at")
        qs.filter(receiver=user, is_read=False).update(is_read=True)
        return JsonResponse({"messages": [{
            "id": m.id, "sender_id": m.sender_id, "receiver_id": m.receiver_id,
            "text": m.text, "created_at": m.created_at.isoformat(), "is_read": m.is_read,
        } for m in qs[:300]]})
    data = _json(request)
    text = (data.get("text") or "").strip()
    if not text:
        return JsonResponse({"detail": "Mensaje vacío."}, status=400)
    patient, doctor = chat_pair(user, other)
    conversation, _ = Conversation.objects.get_or_create(patient=patient, doctor=doctor)
    m = ChatMessage.objects.create(conversation=conversation, sender=user, receiver=other, text=text)
    Notification.objects.create(user=other, title="Nuevo mensaje", message=f"Tienes un mensaje de {user.get_full_name() or user.username}.", notification_type="new_message")
    return JsonResponse({"message": {"id": m.id, "text": m.text, "created_at": m.created_at.isoformat()}}, status=201)


@csrf_exempt
@bearer_required
@require_http_methods(["GET", "POST", "OPTIONS"])
def notifications_api(request):
    user = request.api_user
    if request.method == "POST":
        Notification.objects.filter(user=user, is_read=False).update(is_read=True)
        return JsonResponse({"ok": True})
    qs = Notification.objects.filter(user=user)[:100]
    return JsonResponse({"notifications": [{
        "id": n.id, "title": n.title, "message": n.message, "type": n.notification_type,
        "created_at": n.created_at.isoformat(), "is_read": n.is_read,
    } for n in qs]})


@csrf_exempt
@bearer_required
@require_http_methods(["POST", "OPTIONS"])
def video_call_api(request, appointment_id):
    user = request.api_user
    a = get_object_or_404(Appointment, pk=appointment_id)
    if user.id not in {a.patient_id, a.doctor_id}:
        return JsonResponse({"detail": "Sin permiso."}, status=403)
    if a.status != "approved" or a.modalidad != "online":
        return JsonResponse({"detail": "La videollamada requiere una cita online aprobada."}, status=400)
    call, _ = VideoCall.objects.get_or_create(appointment=a)
    return JsonResponse({"video_call": {"id": call.id, "room_key": f"cap-appointment-{a.id}", "status": call.status}})
