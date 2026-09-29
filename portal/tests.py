from urllib.parse import urlsplit
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.mail import send_mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, CallSignal, DoctorProfile, PatientProfile, VideoCall

User = get_user_model()


class BaseStabilityTests(TestCase):
    def test_removed_admin_route_cannot_create_users(self):
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method("/crear-admin/")
                self.assertEqual(response.status_code, 404)
                self.assertFalse(User.objects.exists())

    def test_admin_doctor_list_renders_in_name_order(self):
        admin = User.objects.create_user(username="staff", is_staff=True)
        for name in ("Zoe", "Ana"):
            user = User.objects.create_user(username=name, first_name=name)
            DoctorProfile.objects.create(user=user, especialidad="Psicología", cedula=name)
        self.client.force_login(admin)
        response = self.client.get(reverse("doctor_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [doctor.user.first_name for doctor in response.context["doctores"]],
            ["Ana", "Zoe"],
        )

    def test_doctor_list_rejects_non_staff_user(self):
        user = User.objects.create_user(username="patient")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("doctor_list")).status_code, 403)

    def test_profile_update_preserves_activation_state(self):
        user = User.objects.create_user(username="doctor")
        user.groups.add(Group.objects.create(name="Doctores"))
        doctor = DoctorProfile.objects.create(
            user=user, especialidad="Psicología", cedula="123"
        )
        self.client.force_login(user)
        for active, supplied in ((True, {}), (False, {}), (False, {"activo": "on"})):
            with self.subTest(active=active, supplied=supplied):
                doctor.activo = active
                doctor.save(update_fields=["activo"])
                response = self.client.post(reverse("portal_settings"), {
                    "full_name": "Doctor Prueba",
                    "especialidad": "Psicología clínica",
                    "cedula": "123",
                    "experiencia_anios": "4",
                    "biografia": "Perfil actualizado",
                    **supplied,
                })
                self.assertRedirects(response, reverse("portal_settings"))
                doctor.refresh_from_db()
                self.assertEqual(doctor.activo, active)
                self.assertEqual(doctor.biografia, "Perfil actualizado")


class VideoCallsTests(TestCase):
    def setUp(self):
        patient_group = Group.objects.create(name="Pacientes")
        doctor_group = Group.objects.create(name="Doctores")
        self.patient = User.objects.create_user("patient-calls", email="patient-calls@example.com")
        self.patient.groups.add(patient_group)
        PatientProfile.objects.create(user=self.patient)
        self.doctor = User.objects.create_user("doctor-calls", email="doctor-calls@example.com")
        self.doctor.groups.add(doctor_group)
        DoctorProfile.objects.create(user=self.doctor, especialidad="Psicología", cedula="CALL-1")
        start = timezone.now() + timedelta(days=1)
        self.appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, start_at=start,
            end_at=start + timedelta(hours=1), modalidad="online", status="approved",
        )

    def test_patient_sees_approved_video_call(self):
        self.client.force_login(self.patient)
        response = self.client.get(reverse("video_calls"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("video_room", args=[self.appointment.id]))

    def test_unrelated_patient_cannot_enter_video_call(self):
        other = User.objects.create_user("other-patient")
        other.groups.add(Group.objects.get(name="Pacientes"))
        PatientProfile.objects.create(user=other)
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("video_room", args=[self.appointment.id])).status_code,
            403,
        )

    def test_ended_call_restarts_and_removes_old_signals(self):
        call = VideoCall.objects.create(
            appointment=self.appointment, status="ended",
            started_at=timezone.now() - timedelta(hours=1), ended_at=timezone.now(),
        )
        CallSignal.objects.create(
            room_key=f"cap-appointment-{self.appointment.id}", sender=self.doctor,
            payload={"type": "offer", "sdp": {"type": "offer", "sdp": "old"}},
        )
        self.client.force_login(self.patient)
        response = self.client.get(reverse("video_room", args=[self.appointment.id]))
        self.assertEqual(response.status_code, 200)
        call.refresh_from_db()
        self.assertEqual(call.status, "in_progress")
        self.assertIsNone(call.ended_at)
        self.assertFalse(CallSignal.objects.filter(
            room_key=f"cap-appointment-{self.appointment.id}"
        ).exists())
        self.assertFalse(response.context["is_initiator"])

    def test_doctor_starts_a_clean_negotiation(self):
        CallSignal.objects.create(
            room_key=f"cap-appointment-{self.appointment.id}", sender=self.patient,
            payload={"type": "ready"},
        )
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("video_room", args=[self.appointment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_initiator"])
        self.assertFalse(CallSignal.objects.filter(
            room_key=f"cap-appointment-{self.appointment.id}"
        ).exists())


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.email = "testuser@example.com"
        self.password = "OldPass123!"
        self.user = User.objects.create_user(
            username=self.email,
            email=self.email,
            password=self.password,
        )
        patients, _ = Group.objects.get_or_create(name="Pacientes")
        self.user.groups.add(patients)
        from .models import PatientProfile
        PatientProfile.objects.get_or_create(user=self.user)

    def test_password_reset_page_loads(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recuperar contraseña")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEBUG=False,
        RENDER_EXTERNAL_HOSTNAME="cap-online.onrender.com",
        DEFAULT_FROM_EMAIL="viridianahernandez02635@gmail.com",
    )
    def test_password_reset_email_is_sent_for_registered_user(self):
        response = self.client.post(reverse("password_reset"), {"email": self.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.email, mail.outbox[0].to)
        self.assertTrue(mail.outbox[0].subject.strip())
        self.assertNotIn("\n", mail.outbox[0].subject)
        self.assertIn("https://cap-online.onrender.com/reset/", mail.outbox[0].body)
        self.assertNotIn("localhost", mail.outbox[0].body)
        self.assertNotIn("127.0.0.1", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEBUG=False,
        RENDER_EXTERNAL_HOSTNAME="cap-online.onrender.com",
        DEFAULT_FROM_EMAIL="viridianahernandez02635@gmail.com",
    )
    def test_password_reset_link_changes_password_and_allows_login(self):
        self.client.post(reverse("password_reset"), {"email": self.email})
        self.assertEqual(len(mail.outbox), 1)

        reset_url = next(
            line.strip()
            for line in mail.outbox[0].body.splitlines()
            if line.strip().startswith("https://")
        )
        self.assertEqual(urlsplit(reset_url).netloc, "cap-online.onrender.com")
        reset_path = urlsplit(reset_url).path

        response = self.client.get(reset_path, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nueva contraseña")

        post_path = reset_path
        if response.redirect_chain:
            post_path = response.redirect_chain[-1][0]

        response = self.client.post(
            post_path,
            {
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        user = User.objects.get(email=self.email)
        self.assertTrue(user.check_password("NewPass123!"))

        login_response = self.client.post(
            reverse("login"),
            {"email": self.email, "password": "NewPass123!"},
        )
        self.assertRedirects(
            login_response,
            reverse("portal_dashboard"),
            fetch_redirect_response=False,
        )
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_inactive_user_does_not_receive_password_reset_email(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(reverse("password_reset"), {"email": self.email})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_direct_send_mail_works_without_silencing_errors(self):
        sent_count = send_mail(
            "Prueba de envío",
            "Este es un correo de prueba.",
            "viridianahernandez02635@gmail.com",
            [self.email],
            fail_silently=False,
        )
        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Prueba de envío")
        self.assertIn(self.email, mail.outbox[0].to)
