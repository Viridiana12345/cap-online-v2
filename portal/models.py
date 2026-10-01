from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ValidationError
from cloudinary.models import CloudinaryField


class PatientProfile(models.Model):
    """Datos extra para pacientes."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient_profile")
    telefono = models.CharField(max_length=30, blank=True)
    biografia = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PatientProfile({self.user.username})"


class DoctorProfile(models.Model):
    MODALIDAD_CHOICES = [
        ("online", "Online"),
        ("presencial", "Presencial"),
        ("ambos", "Online y Presencial"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="doctor_profile"
    )
    especialidad = models.CharField(max_length=120)
    cedula = models.CharField(max_length=80)
    biografia = models.TextField(blank=True)
    experiencia_anios = models.IntegerField(default=0)

    # NUEVOS CAMPOS
    telefono = models.CharField(max_length=20, blank=True)
    modalidad = models.CharField(max_length=20, choices=MODALIDAD_CHOICES, default="online")
    duracion_sesion = models.PositiveIntegerField(default=60, help_text="Duración en minutos")
    horario_inicio = models.TimeField(blank=True, null=True)
    horario_fin = models.TimeField(blank=True, null=True)
    idiomas = models.CharField(max_length=120, blank=True, help_text="Ej. Español, Inglés")
    costo_consulta = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)

    foto = CloudinaryField(
        "foto",
        resource_type="image",
        folder="cap_online/doctores",
        blank=True,
        null=True,
    )
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} - {self.especialidad}"


class ChatMessage(models.Model):
    # Opcional durante la transición: conservar mensajes históricos y el chat actual.
    conversation = models.ForeignKey(
        "Conversation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="messages",
    )
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_messages")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def clean(self):
        super().clean()
        if self.conversation_id:
            participants = {self.conversation.patient_id, self.conversation.doctor.user_id}
            if {self.sender_id, self.receiver_id} != participants:
                raise ValidationError("El mensaje debe pertenecer a los participantes de la conversación.")

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username}: {self.text[:20]}"


class CallRequest(models.Model):
    CALL_TYPES = (
        ("audio", "Audio"),
        ("video", "Video"),
    )

    STATUS = (
        ("pending", "Pendiente"),
        ("approved", "Aceptada"),
        ("in_progress", "En curso"),
        ("rejected", "Rechazada"),
        ("done", "Finalizada"),
        ("cancelled", "Cancelada"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="call_requests"
    )

    doctor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_calls"
    )

    call_type = models.CharField(
        max_length=10,
        choices=CALL_TYPES,
        default="audio"
    )

    scheduled_for = models.DateTimeField(
        null=True,
        blank=True
    )

    notes = models.CharField(
        max_length=255,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    started_at = models.DateTimeField(
        null=True,
        blank=True
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.call_type} - {self.status}"

class Appointment(models.Model):
    STATUS = (
        ("pending", "Pendiente"),
        ("approved", "Aprobada"),
        ("rejected", "Rechazada"),
        ("done", "Realizada"),
        ("cancelled", "Cancelada"),
        ("rescheduled", "Reprogramada"),
    )

    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="appointments_as_patient")
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="appointments_as_doctor")

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    notes = models.CharField(max_length=255, blank=True)

    # notes conserva el motivo actual; no duplicarlo ni renombrarlo.
    modalidad = models.CharField(
        max_length=20, choices=[("online", "Online"), ("presencial", "Presencial")],
        blank=True, default="",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cancelled_appointments",
    )
    cancellation_reason = models.TextField(blank=True, default="")
    # La nueva cita apunta a la anterior: no sobrescribir las fechas históricas.
    rescheduled_from = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rescheduled_to",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_at"]

    def clean(self):
        super().clean()
        if self.rescheduled_from_id:
            previous = self.rescheduled_from
            if previous.pk == self.pk:
                raise ValidationError("Una cita no puede ser su propia cita anterior.")
            if (previous.patient_id, previous.doctor_id) != (self.patient_id, self.doctor_id):
                raise ValidationError("La reprogramación debe conservar paciente y doctor.")

    def __str__(self):
        return f"{self.patient.username} -> {self.doctor.username}"

class CallSignal(models.Model):
    """Señalización simple (SDP/ICE) para WebRTC usando polling."""
    room_key = models.CharField(max_length=80, db_index=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

#Notas
class SessionNote(models.Model):
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='doctor_notes')
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patient_notes')
    appointment = models.ForeignKey('Appointment', on_delete=models.SET_NULL, null=True, blank=True)

    titulo = models.CharField(max_length=200)
    estado_emocional = models.CharField(max_length=120, blank=True)
    observaciones = models.TextField()
    recomendaciones = models.TextField(blank=True)
    proxima_sesion = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.patient} - {self.titulo}"

class AuditLog(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.CharField(max_length=255)
    modulo = models.CharField(max_length=100, blank=True, null=True)
    ip = models.GenericIPAddressField(blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario} - {self.accion} - {self.fecha}"


class DoctorAvailability(models.Model):
    WEEKDAYS = [(0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"),
                (4, "Viernes"), (5, "Sábado"), (6, "Domingo")]

    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.CASCADE, related_name="availability",
    )
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__gte=0, weekday__lte=6),
                                   name="availability_valid_weekday"),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")),
                                   name="availability_positive_interval"),
        ]


class Conversation(models.Model):
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="conversations_as_patient",
    )
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.PROTECT, related_name="conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "doctor"],
                                    name="unique_patient_doctor_conversation"),
        ]

    def clean(self):
        super().clean()
        if self.patient_id and self.doctor_id and self.patient_id == self.doctor.user_id:
            raise ValidationError("Paciente y doctor deben ser usuarios diferentes.")


class Notification(models.Model):
    TYPES = [
        ("appointment_confirmed", "Cita confirmada"),
        ("appointment_changed", "Cita modificada"),
        ("appointment_cancelled", "Cita cancelada"),
        ("new_message", "Nuevo mensaje"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=TYPES)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-pk"]


class VideoCall(models.Model):
    """Estructura opcional independiente de proveedores y de llamadas históricas."""
    appointment = models.OneToOneField(
        Appointment, on_delete=models.PROTECT, related_name="video_call",
    )
    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pendiente"), ("in_progress", "En curso"),
                 ("ended", "Finalizada"), ("cancelled", "Cancelada")],
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)


class MobileToken(models.Model):
    """Hashed bearer tokens for the native/mobile client.

    Only a SHA-256 digest is stored. The raw token is returned once at login.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mobile_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"MobileToken({self.user_id}, revoked={self.revoked})"
