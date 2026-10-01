from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin import CAPUserChangeForm
from .models import Appointment, ChatMessage, Conversation, DoctorProfile, PatientProfile, SessionNote
from .permissions import is_admin, is_doctor, is_patient


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RolePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Cactus!River-6942"
        patients = Group.objects.create(name="Pacientes")
        doctors = Group.objects.create(name="Doctores")
        cls.patient = User.objects.create_user("patient", "patient@example.com", cls.password)
        cls.other_patient = User.objects.create_user("other", "other@example.com", cls.password)
        for user in (cls.patient, cls.other_patient):
            user.groups.add(patients)
            PatientProfile.objects.create(user=user)
        cls.doctor = User.objects.create_user("doctor", "doctor@example.com", cls.password)
        cls.other_doctor = User.objects.create_user("otherdoctor", "otherdoctor@example.com", cls.password)
        for user in (cls.doctor, cls.other_doctor):
            user.groups.add(doctors)
            DoctorProfile.objects.create(user=user, especialidad="Psicología", cedula=user.username)
        cls.admin = User.objects.create_user("rh", "rh@example.com", cls.password, is_staff=True)
        cls.unassigned = User.objects.create_user("unassigned", "unassigned@example.com", cls.password)
        cls.start = timezone.now() + timedelta(days=1)
        cls.appointment = Appointment.objects.create(
            patient=cls.patient, doctor=cls.doctor, start_at=cls.start,
            end_at=cls.start + timedelta(hours=1), status="approved", notes="own-appointment",
        )
        cls.other_appointment = Appointment.objects.create(
            patient=cls.other_patient, doctor=cls.other_doctor, start_at=cls.start,
            end_at=cls.start + timedelta(hours=1), status="approved", notes="private-appointment",
        )
        cls.note = SessionNote.objects.create(
            doctor=cls.doctor, patient=cls.patient, titulo="Confidencial", observaciones="clinical-secret",
        )

    def login_as(self, user):
        self.client.force_login(user)

    def registration(self, **extra):
        data = {"full_name": "Nueva Persona", "email": "new@example.com",
                "password": self.password, "password2": self.password, "acepto_politicas": "on"}
        data.update(extra)
        return self.client.post(reverse("signup"), data)

    def doctor_data(self, **extra):
        data = {"first_name": "Nueva", "last_name": "Doctora", "email": "newdoc@example.com",
                "password": self.password, "password2": self.password,
                "especialidad": "Psicología", "cedula": "123", "activo": "on"}
        data.update(extra)
        return data

    def test_role_helpers_do_not_create_groups(self):
        before = Group.objects.count()
        self.assertTrue(is_patient(self.patient))
        self.assertTrue(is_doctor(self.doctor))
        self.assertTrue(is_admin(self.admin))
        self.assertFalse(is_patient(self.unassigned))
        self.assertFalse(is_doctor(self.patient))
        self.assertEqual(Group.objects.count(), before)

    def test_public_signup_cannot_escalate_role(self):
        self.registration(email=" New@Example.COM ", is_staff="True", is_superuser="True", role="Doctor")
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.username, "new@example.com")
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Pacientes"])
        self.assertTrue(PatientProfile.objects.filter(user=user).exists())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertFalse(DoctorProfile.objects.filter(user=user).exists())

    def test_signup_rejects_invalid_duplicate_and_weak_credentials(self):
        before = User.objects.count()
        for data in ({"email": "not-an-email"}, {"email": "PATIENT@EXAMPLE.COM"},
                     {"password": "123", "password2": "123"}, {"password2": "different"},
                     {"acepto_politicas": ""}):
            with self.subTest(data=data):
                self.registration(**data)
                self.assertEqual(User.objects.count(), before)

    def test_signup_rolls_back_user_if_profile_fails(self):
        with patch("portal.views.PatientProfile.objects.create", side_effect=IntegrityError):
            response = self.registration()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_doctor_creation_requires_admin(self):
        for user in (self.patient, self.doctor, self.unassigned):
            self.login_as(user)
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(reverse("doctor_create"), self.doctor_data()).status_code, 403)
        self.assertFalse(User.objects.filter(email="newdoc@example.com").exists())
        self.login_as(self.admin)
        response = self.client.post(reverse("doctor_create"), self.doctor_data())
        self.assertRedirects(response, reverse("doctor_list"))
        user = User.objects.get(email="newdoc@example.com")
        self.assertTrue(is_doctor(user))
        self.assertFalse(user.is_staff)
        self.assertFalse(PatientProfile.objects.filter(user=user).exists())

    def test_doctor_creation_validates_password_and_duplicate_email(self):
        self.login_as(self.admin)
        before = User.objects.count()
        for extra in ({"email": "PATIENT@example.com"}, {"password": "123", "password2": "123"}):
            response = self.client.post(reverse("doctor_create"), self.doctor_data(**extra))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(User.objects.count(), before)

    def test_login_routes_each_role(self):
        for user, target in ((self.patient, "portal_dashboard"), (self.doctor, "portal_dashboard"),
                             (self.admin, "doctor_list")):
            self.client.logout()
            response = self.client.post(reverse("login"), {"email": user.email.upper(), "password": self.password})
            self.assertRedirects(response, reverse(target))
            if target == "portal_dashboard":
                self.assertEqual(self.client.get(reverse(target)).context["is_doctor"], user == self.doctor)

    def test_login_duplicate_email_does_not_choose_an_account(self):
        User.objects.create_user("duplicate", self.patient.email.upper(), self.password)
        response = self.client.post(reverse("login"), {"email": self.patient.email, "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["login_error"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_login(self):
        self.patient.is_active = False
        self.patient.save()
        self.client.post(reverse("login"), {"email": self.patient.email, "password": self.password})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unassigned_user_cannot_login_to_portal(self):
        response = self.client.post(
            reverse("login"),
            {"email": self.unassigned.email, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acceso no habilitado")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_email_form_rejects_duplicate(self):
        form = CAPUserChangeForm(instance=self.other_patient)
        form.cleaned_data = {"email": self.patient.email.upper()}
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            form.clean_email()

    def test_duplicate_email_reset_sends_no_tokens(self):
        User.objects.create_user("duplicate", self.patient.email.upper(), self.password)
        response = self.client.post(reverse("password_reset"), {"email": self.patient.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_anonymous_and_unassigned_access(self):
        urls = [reverse(name) for name in ("portal_dashboard", "portal_settings", "portal_chat",
                "portal_notifications", "portal_calendar_patient", "doctor_list", "mis_notas_clinicas")]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.login_as(self.unassigned)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_patient_sees_only_own_appointments_and_notifications(self):
        self.login_as(self.patient)
        for name in ("portal_calendar_patient", "portal_notifications"):
            response = self.client.get(reverse(name), {"patient_id": self.other_patient.pk})
            self.assertEqual(list(response.context["appointments"]), [self.appointment])
        self.assertEqual(self.client.get(reverse("portal_calendar_doctor")).status_code, 403)

    def test_doctor_sees_only_assigned_appointments(self):
        self.login_as(self.doctor)
        response = self.client.get(reverse("portal_calendar_doctor"))
        self.assertEqual(list(response.context["appointments"]), [self.appointment])

    def test_patient_profile_update_ignores_other_user_ids(self):
        self.login_as(self.patient)
        response = self.client.post(reverse("portal_settings"), {
            "user_id": self.other_patient.pk, "full_name": "Mi Nombre", "telefono": "111",
            "biografia": "Mi perfil", "is_staff": "True",
        })
        self.assertRedirects(response, reverse("portal_settings"))
        self.other_patient.patient_profile.refresh_from_db()
        self.patient.patient_profile.refresh_from_db()
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.patient_profile.telefono, "111")
        self.assertEqual(self.other_patient.patient_profile.telefono, "")
        self.assertFalse(self.patient.is_staff)

    def test_doctor_settings_do_not_create_patient_profile(self):
        self.login_as(self.doctor)
        self.assertEqual(self.client.get(reverse("portal_settings")).status_code, 200)
        self.assertFalse(PatientProfile.objects.filter(user=self.doctor).exists())

    def test_appointment_status_only_assigned_doctor_and_valid_transition(self):
        url = reverse("appointment_update_status", args=[self.appointment.pk, "done"])
        self.login_as(self.patient)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.login_as(self.other_doctor)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "approved")
        self.login_as(self.doctor)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("portal_calendar_doctor"))
        self.assertEqual(self.client.post(url).status_code, 400)

    def test_appointment_creation_forces_owner_and_pending_state(self):
        self.login_as(self.patient)
        data = {"doctor": self.doctor.pk, "patient": self.other_patient.pk, "status": "approved",
                "start_at": "2027-01-01T10:00", "end_at": "2027-01-01T11:00", "notes": "new"}
        self.client.post(reverse("appointment_create"), data)
        appointment = Appointment.objects.get(notes="new")
        self.assertEqual(appointment.patient, self.patient)
        self.assertEqual(appointment.status, "pending")
        self.login_as(self.doctor)
        self.assertEqual(self.client.post(reverse("appointment_create"), data).status_code, 403)

    def test_patient_cannot_read_or_create_clinical_notes(self):
        self.login_as(self.patient)
        for url in (reverse("mis_notas_clinicas"), reverse("notas_paciente", args=[self.patient.pk])):
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(url).status_code, 403)
        self.assertEqual(SessionNote.objects.count(), 1)

    def test_doctor_cannot_read_or_create_notes_for_unrelated_patient(self):
        self.login_as(self.doctor)
        url = reverse("notas_paciente", args=[self.other_patient.pk])
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(url, {"titulo": "No", "observaciones": "No"}).status_code, 403)
        self.assertEqual(SessionNote.objects.count(), 1)

    def test_pending_appointment_does_not_grant_clinical_access(self):
        self.appointment.status = "pending"
        self.appointment.save()
        self.login_as(self.doctor)
        self.assertEqual(self.client.get(reverse("notas_paciente", args=[self.patient.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("mis_notas_clinicas")), "clinical-secret")

    def test_authorized_doctor_notes_are_scoped_and_creation_ignores_forged_owner(self):
        other_note = SessionNote.objects.create(doctor=self.other_doctor, patient=self.patient,
                                               titulo="Ajena", observaciones="other-secret")
        self.login_as(self.doctor)
        response = self.client.get(reverse("mis_notas_clinicas"))
        self.assertContains(response, "clinical-secret")
        self.assertNotContains(response, "other-secret")
        url = reverse("notas_paciente", args=[self.patient.pk])
        response = self.client.post(url, {"titulo": "Nueva", "observaciones": "Seguimiento",
                                         "doctor": self.other_doctor.pk, "patient": self.other_patient.pk})
        self.assertRedirects(response, url)
        note = SessionNote.objects.get(titulo="Nueva")
        self.assertEqual((note.doctor_id, note.patient_id), (self.doctor.pk, self.patient.pk))

    def test_all_chat_routes_reject_unrelated_ids(self):
        for sender, receiver in ((self.patient, self.other_patient), (self.patient, self.other_doctor),
                                 (self.doctor, self.other_patient), (self.doctor, self.other_doctor)):
            self.login_as(sender)
            for name in ("portal_chat_with", "chat_thread_api"):
                self.assertEqual(self.client.get(reverse(name, args=[receiver.pk])).status_code, 404)
            for name in ("send_message", "chat_send_api"):
                self.assertEqual(self.client.post(reverse(name, args=[receiver.pk]), {"text": "denied"}).status_code, 404)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(Conversation.objects.exists())

    def test_historical_message_does_not_grant_access_or_become_read(self):
        message = ChatMessage.objects.create(sender=self.other_doctor, receiver=self.patient, text="unauthorized-history")
        self.login_as(self.patient)
        self.assertEqual(self.client.get(reverse("chat_thread_api", args=[self.other_doctor.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("portal_notifications")), "unauthorized-history")
        message.refresh_from_db()
        self.assertFalse(message.is_read)

    def test_related_chat_reads_history_and_links_new_messages(self):
        old = ChatMessage.objects.create(sender=self.doctor, receiver=self.patient, text="historical")
        self.login_as(self.patient)
        response = self.client.get(reverse("chat_thread_api", args=[self.doctor.pk]))
        self.assertEqual(response.json()["messages"][0]["text"], "historical")
        old.refresh_from_db()
        self.assertTrue(old.is_read)
        self.assertIsNone(old.conversation_id)
        response = self.client.post(reverse("chat_send_api", args=[self.doctor.pk]), {"text": "new"})
        self.assertEqual(response.status_code, 200)
        new = ChatMessage.objects.get(pk=response.json()["id"])
        self.assertEqual(new.conversation.patient, self.patient)
        self.assertEqual(new.conversation.doctor.user, self.doctor)

    def test_existing_conversation_allows_chat_but_not_clinical_notes(self):
        Conversation.objects.create(patient=self.patient, doctor=self.other_doctor.doctor_profile)
        self.login_as(self.patient)
        self.assertEqual(self.client.post(reverse("chat_send_api", args=[self.other_doctor.pk]), {"text": "hello"}).status_code, 200)
        self.login_as(self.other_doctor)
        self.assertEqual(self.client.get(reverse("notas_paciente", args=[self.patient.pk])).status_code, 403)

    def test_doctor_chat_contacts_exclude_unrelated_patients(self):
        self.login_as(self.doctor)
        response = self.client.get(reverse("portal_chat"))
        self.assertEqual(list(response.context["users"]), [self.patient])

    def test_admin_without_doctor_role_cannot_access_clinical_admin(self):
        self.admin.is_superuser = True
        self.admin.save()
        self.login_as(self.admin)
        response = self.client.get(reverse("admin:portal_sessionnote_changelist"))
        self.assertEqual(response.status_code, 403)
