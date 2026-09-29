from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class RegistrationFeedbackTests(TestCase):
    def test_invalid_names_cannot_create_accounts(self):
        for name in ("kwhdhsqvcjadhcjhascvj", "Ana123 López", "Ana _López", "Aaaaa López", "Ana - López"):
            with self.subTest(name=name):
                response = self.client.post(reverse("signup"), self.data(full_name=name))
                self.assertIn("full_name", response.context["form"].errors)
                self.assertFalse(User.objects.exists())

    def test_names_support_accents_and_compound_surnames(self):
        from .forms import PatientRegistrationForm
        for name in ("María José López", "Anne-Marie O’Neill", "José de la Cruz", "李 明", "Jose\u0301 López"):
            with self.subTest(name=name):
                form = PatientRegistrationForm(self.data(full_name=name))
                self.assertTrue(form.is_valid(), form.errors)
        form = PatientRegistrationForm(self.data(full_name="  Ana   López  "))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["full_name"], "Ana López")

    def data(self, **changes):
        return {"full_name": "Ana López", "email": "ana@example.com",
                "password": "River!Forest837", "password2": "River!Forest837",
                "acepto_politicas": "on", **changes}

    def test_real_fields_and_privacy_are_rendered(self):
        response = self.client.get(reverse("signup"))
        for name in ("telefono", "biografia", "acepto_politicas"):
            self.assertContains(response, f'name="{name}"')
        self.assertNotContains(response, 'id="submitBtn" disabled')

    def test_empty_submission_gives_field_instructions(self):
        response = self.client.post(reverse("signup"), {})
        self.assertEqual(set(response.context["form"].errors),
                         {"full_name", "email", "password", "password2", "acepto_politicas"})
        self.assertContains(response, "Ingresa tu nombre completo")
        self.assertFalse(User.objects.exists())

    def test_duplicate_email_explains_recovery_and_preserves_name(self):
        User.objects.create_user("existing", "ana@example.com", "SomePassword!")
        response = self.client.post(reverse("signup"), self.data())
        self.assertContains(response, "recupera tu contraseña")
        self.assertContains(response, 'value="Ana López"')
        self.assertNotContains(response, "River!Forest837")

    def test_mismatch_and_missing_consent_block_creation(self):
        response = self.client.post(reverse("signup"), self.data(password2="different", acepto_politicas=""))
        self.assertIn("password2", response.context["form"].errors)
        self.assertIn("acepto_politicas", response.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_invalid_phone_is_explained(self):
        response = self.client.post(reverse("signup"), self.data(telefono="abc123"))
        self.assertContains(response, "Usa solo dígitos")
        self.assertFalse(User.objects.exists())

    def test_optional_phone_can_be_empty_and_registration_succeeds(self):
        response = self.client.post(reverse("signup"), self.data())
        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(email="ana@example.com")
        self.assertTrue(user.groups.filter(name="Pacientes").exists())

    def test_specific_password_errors(self):
        for password, message in (("", "Ingresa una contraseña."), ("abc", "Usa al menos 8 caracteres."),
                                  ("Abcd efgh12", "no debe contener espacios"),
                                  ("1234567890", "solo números"),
                                  ("ANA@example.com", "no puede ser tu correo")):
            with self.subTest(password=password):
                response = self.client.post(reverse("signup"), self.data(password=password, password2=password))
                self.assertContains(response, message)
                self.assertIn("password", response.context["form"].errors)
                self.assertFalse(User.objects.exists())
