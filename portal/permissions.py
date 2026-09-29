"""Roles y alcance de acceso del portal; consultar permisos nunca crea grupos."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import F, Q

from .models import Appointment, Conversation, DoctorProfile


def is_admin(user):
    return bool(user.is_authenticated and user.is_active and (user.is_staff or user.is_superuser))


def is_doctor(user):
    return bool(user.is_authenticated and user.is_active
                and user.groups.filter(name="Doctores").exists()
                and DoctorProfile.objects.filter(user=user).exists())


def is_patient(user):
    return bool(user.is_authenticated and user.is_active and not is_admin(user)
                and not user.groups.filter(name="Doctores").exists()
                and user.groups.filter(name="Pacientes").exists())


def role_required(*checks):
    def decorate(view):
        @login_required(login_url="login")
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not any(check(request.user) for check in checks):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


portal_required = role_required(is_patient, is_doctor)
patient_required = role_required(is_patient)
doctor_required = role_required(is_doctor)
admin_required = role_required(is_admin)


def care_patient_ids(doctor):
    return Appointment.objects.filter(
        doctor=doctor, status__in=("approved", "done"),
    ).values_list("patient_id", flat=True)


def has_care_relationship(doctor, patient):
    return (is_doctor(doctor) and is_patient(patient)
            and Appointment.objects.filter(doctor=doctor, patient=patient,
                                           status__in=("approved", "done")).exists())


def chat_contacts(user):
    if is_doctor(user):
        conversations = Conversation.objects.filter(doctor__user=user).values_list("patient_id", flat=True)
        return User.objects.filter(is_active=True, groups__name="Pacientes").filter(
            Q(pk__in=care_patient_ids(user)) | Q(pk__in=conversations)
        ).exclude(groups__name="Doctores").exclude(is_staff=True).exclude(is_superuser=True).distinct()
    if is_patient(user):
        doctors = Appointment.objects.filter(patient=user, status__in=("approved", "done")).values_list("doctor_id", flat=True)
        conversations = Conversation.objects.filter(patient=user).values_list("doctor__user_id", flat=True)
        return User.objects.filter(is_active=True, groups__name="Doctores", doctor_profile__isnull=False).filter(
            Q(pk__in=doctors) | Q(pk__in=conversations)
        ).distinct()
    return User.objects.none()


def chat_pair(user, other):
    if not chat_contacts(user).filter(pk=other.pk).exists():
        raise PermissionDenied
    patient, doctor = (other, user) if is_doctor(user) else (user, other)
    return patient, doctor.doctor_profile


def thread_messages(user, other):
    from .models import ChatMessage
    patient, doctor = chat_pair(user, other)
    return ChatMessage.objects.filter(
        Q(sender=user, receiver=other) | Q(sender=other, receiver=user)
    ).filter(Q(conversation__isnull=True) | Q(conversation__patient=patient, conversation__doctor=doctor))


def visible_messages(user):
    from .models import ChatMessage
    messages = ChatMessage.objects.filter(receiver=user, sender__in=chat_contacts(user))
    if is_doctor(user):
        return messages.filter(Q(conversation__isnull=True) | Q(
            conversation__doctor__user=user, conversation__patient_id=F("sender_id")))
    return messages.filter(Q(conversation__isnull=True) | Q(
        conversation__patient=user, conversation__doctor__user_id=F("sender_id")))
