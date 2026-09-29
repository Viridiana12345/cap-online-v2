from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from django.utils import timezone
from portal.models import (
    Appointment, Conversation, DoctorAvailability, DoctorProfile,
    PatientProfile, ChatMessage, Notification,
)


class Command(BaseCommand):
    help = "Crea usuarios y datos de demostración idempotentes para CAP Online."

    def handle(self, *args, **options):
        gp, _ = Group.objects.get_or_create(name="Pacientes")
        gd, _ = Group.objects.get_or_create(name="Doctores")

        patient, created = User.objects.get_or_create(
            username="paciente@caponline.local",
            defaults={"email": "paciente@caponline.local", "first_name": "Fernanda", "last_name": "Paciente"},
        )
        patient.email = "paciente@caponline.local"
        patient.first_name = "Fernanda"; patient.last_name = "Paciente"
        patient.set_password("Paciente123!"); patient.save(); patient.groups.add(gp)
        PatientProfile.objects.get_or_create(user=patient, defaults={"telefono": "8110000000"})

        doctor, _ = User.objects.get_or_create(
            username="doctora@caponline.local",
            defaults={"email": "doctora@caponline.local", "first_name": "Elena", "last_name": "Ruiz"},
        )
        doctor.email = "doctora@caponline.local"
        doctor.first_name = "Elena"; doctor.last_name = "Ruiz"
        doctor.set_password("Doctora123!"); doctor.save(); doctor.groups.add(gd)
        profile, _ = DoctorProfile.objects.get_or_create(
            user=doctor,
            defaults={
                "especialidad": "Psicología clínica", "cedula": "DEMO-001",
                "biografia": "Acompañamiento psicológico con enfoque humano y práctico.",
                "experiencia_anios": 8, "modalidad": "ambos", "idiomas": "Español",
                "costo_consulta": 450, "activo": True,
            },
        )
        for weekday in range(0, 5):
            DoctorAvailability.objects.get_or_create(
                doctor=profile, weekday=weekday,
                defaults={"start_time": "09:00", "end_time": "18:00", "active": True},
            )

        start = timezone.now() + timedelta(days=1)
        start = start.replace(hour=10, minute=0, second=0, microsecond=0)
        appt = Appointment.objects.filter(patient=patient, doctor=doctor, status="approved").first()
        if not appt:
            appt = Appointment.objects.create(
                patient=patient, doctor=doctor, start_at=start, end_at=start + timedelta(hours=1),
                notes="Sesión de seguimiento", modalidad="online", status="approved",
            )
        conv, _ = Conversation.objects.get_or_create(patient=patient, doctor=profile)
        if not ChatMessage.objects.filter(conversation=conv).exists():
            ChatMessage.objects.create(conversation=conv, sender=doctor, receiver=patient, text="Hola, ¿cómo te has sentido esta semana?")
            ChatMessage.objects.create(conversation=conv, sender=patient, receiver=doctor, text="Me he sentido mejor, gracias.")
        Notification.objects.get_or_create(
            user=patient, title="Cita confirmada", message="Tu cita de demostración está confirmada.",
            notification_type="appointment_confirmed",
        )

        self.stdout.write(self.style.SUCCESS("Datos demo listos."))
        self.stdout.write("Paciente: paciente@caponline.local / Paciente123!")
        self.stdout.write("Doctora: doctora@caponline.local / Doctora123!")
