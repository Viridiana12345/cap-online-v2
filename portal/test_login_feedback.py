from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse


class LoginFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "CorrectHorse!789"
        cls.user = User.objects.create_user("login-test", "patient@example.com", cls.password)
        cls.user.groups.add(Group.objects.create(name="Pacientes"))

    def post(self, **data):
        return self.client.post(reverse("login"), data)

    def test_empty_fields_have_separate_instructions(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["field_errors"]), {"email", "password"})
        self.assertContains(response, "Ingresa tu correo")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_email_preserves_input_and_explains_format(self):
        response = self.post(email="correo-invalido", password=self.password)
        self.assertContains(response, 'value="correo-invalido"')
        self.assertContains(response, "Correo no válido")
        self.assertEqual(set(response.context["field_errors"]), {"email"})
        self.assertNotContains(response, self.password)

    def test_missing_password_points_to_recovery(self):
        response = self.post(email=self.user.email)
        self.assertEqual(set(response.context["field_errors"]), {"password"})
        self.assertContains(response, "Ingresa tu contraseña")

    def test_wrong_credentials_keep_email_without_disclosing_account(self):
        known = self.post(email=self.user.email, password="WrongPassword!")
        unknown = self.post(email="unknown@example.com", password="WrongPassword!")
        self.assertEqual(known.context["login_error"], unknown.context["login_error"])
        self.assertContains(known, 'value="patient@example.com"')
        self.assertContains(known, "Correo o contraseña incorrectos")
        self.assertNotContains(known, "WrongPassword!")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_account_stays_logged_out(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.post(email=self.user.email, password=self.password)
        self.assertTrue(response.context["login_error"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unassigned_account_gets_access_instructions(self):
        self.user.groups.clear()
        response = self.post(email=self.user.email, password=self.password)
        self.assertContains(response, "Contacta a administración")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_valid_credentials_still_sign_in(self):
        response = self.post(email=" PATIENT@EXAMPLE.COM ", password=self.password)
        self.assertRedirects(response, reverse("portal_dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
