import re
import unicodedata

from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password, get_default_password_validators
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Appointment, DoctorAvailability, DoctorProfile, PatientProfile


def validate_unique_email(email, exclude_pk=None):
    email = email.strip().lower()
    matches = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
    if exclude_pk:
        matches = matches.exclude(pk=exclude_pk)
    if matches.exists():
        raise forms.ValidationError("Ese correo ya está registrado.")
    return email


class AccountRegistrationForm(forms.Form):
    email = forms.EmailField(max_length=150)
    password = forms.CharField(strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(strip=False, widget=forms.PasswordInput)

    def clean_email(self):
        return validate_unique_email(self.cleaned_data["email"])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password and password != cleaned.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden. Escribe exactamente la misma contraseña en ambos campos.")
        parts = cleaned.get("full_name", "").split(maxsplit=1)
        user = User(
            username=cleaned.get("email", ""), email=cleaned.get("email", ""),
            first_name=cleaned.get("first_name", parts[0] if parts else ""),
            last_name=cleaned.get("last_name", parts[1] if len(parts) > 1 else ""),
        )
        if password:
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned


class PatientRegistrationForm(AccountRegistrationForm):
    full_name = forms.CharField(max_length=150, label="Nombre completo")
    telefono = forms.CharField(max_length=30, required=False, label="Teléfono")
    biografia = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Sobre ti")
    acepto_politicas = forms.BooleanField(required=True, label="Acepto el aviso de privacidad")

    def clean_full_name(self):
        name = " ".join(unicodedata.normalize("NFC", self.cleaned_data["full_name"]).split())
        if any(not (c.isalpha() or unicodedata.category(c).startswith("M") or c in " -'’") for c in name):
            raise forms.ValidationError("Usa solo letras en tu nombre y apellidos. Se permiten acentos, espacios, guiones y apóstrofos; no números ni otros símbolos.")
        if len(name.split()) < 2:
            raise forms.ValidationError("Escribe tu nombre y al menos un apellido, separados por un espacio. Ejemplo: María López.")
        for part in re.split(r"[\s\-'’]", name):
            if not part or not any(c.isalpha() for c in part):
                raise forms.ValidationError("Revisa los guiones y apóstrofos: deben estar entre las letras del nombre.")
        if re.search(r"(.)\1{3,}", name.casefold()):
            raise forms.ValidationError("Revisa tu nombre: hay una letra repetida cuatro o más veces seguidas. Escribe tu nombre y apellidos sin repeticiones accidentales.")
        return name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.password_min_length = max(
            (getattr(v, "min_length", 0) for v in get_default_password_validators()), default=8
        ) or 8
        self.fields["password"].widget.attrs["minlength"] = self.password_min_length
        errors = {
            "full_name": {"required": "Ingresa tu nombre completo."},
            "email": {"required": "Ingresa tu correo.", "invalid": "El correo no es válido. Usa el formato nombre@correo.com."},
            "password": {"required": "Ingresa una contraseña."},
            "password2": {"required": "Confirma tu contraseña."},
            "acepto_politicas": {"required": "Debes aceptar la Política de Privacidad para crear la cuenta."},
        }
        for name, messages in errors.items():
            self.fields[name].error_messages.update(messages)

    def clean_email(self):
        try:
            return super().clean_email()
        except ValidationError:
            raise forms.ValidationError(
                "Este correo ya tiene una cuenta. Inicia sesión o recupera tu contraseña; también puedes usar otro correo."
            )

    def clean_password(self):
        password = self.cleaned_data["password"]
        if len(password) < self.password_min_length:
            raise forms.ValidationError(f"Usa al menos {self.password_min_length} caracteres.")
        if re.search(r"\s", password):
            raise forms.ValidationError("La contraseña no debe contener espacios.")
        if password.isdecimal():
            raise forms.ValidationError("La contraseña no puede contener solo números. Agrega letras o símbolos.")
        email = self.cleaned_data.get("email", str(self.data.get("email", "")).strip())
        if email and password.lower() == email.lower():
            raise forms.ValidationError("La contraseña no puede ser tu correo. Elige una diferente.")
        return password

    def clean_telefono(self):
        phone = self.cleaned_data["telefono"].strip()
        if phone:
            if not re.fullmatch(r"[+()\d\s.-]+", phone):
                raise forms.ValidationError("Usa solo dígitos, espacios, guiones, paréntesis o el signo + en el teléfono.")
            digits = len(re.sub(r"\D", "", phone))
            if digits < 10:
                raise forms.ValidationError("El teléfono debe tener al menos 10 dígitos.")
            if digits > 15:
                raise forms.ValidationError("El teléfono no debe tener más de 15 dígitos.")
        return phone


class UnambiguousPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        email = email.strip()
        if User.objects.filter(email__iexact=email).count() != 1:
            return []
        return super().get_users(email)


class DoctorCreateForm(AccountRegistrationForm):
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150)
    especialidad = forms.CharField(label="Especialidad", max_length=120)
    cedula = forms.CharField(label="Cédula profesional", max_length=80)
    experiencia_anios = forms.IntegerField(label="Años de experiencia", min_value=0, required=False)
    biografia = forms.CharField(label="Biografía", widget=forms.Textarea(attrs={"rows": 4}), required=False)
    telefono = forms.CharField(label="Teléfono", max_length=20, required=False)
    modalidad = forms.ChoiceField(label="Modalidad", choices=DoctorProfile.MODALIDAD_CHOICES, required=False, initial="online")
    idiomas = forms.CharField(label="Idiomas", max_length=120, required=False)
    costo_consulta = forms.DecimalField(label="Costo de consulta", min_value=0, required=False)
    foto = forms.ImageField(label="Foto", required=False)
    activo = forms.BooleanField(label="Activo", required=False, initial=True)


class DoctorProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = [
            "especialidad", "cedula", "experiencia_anios", "biografia", "foto",
            "telefono", "modalidad", "duracion_sesion", "idiomas", "costo_consulta",
        ]
        widgets = {"biografia": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["modalidad"].required = False
        self.fields["duracion_sesion"].required = False

    def clean_modalidad(self):
        return self.cleaned_data.get("modalidad") or (self.instance.modalidad if self.instance.pk else "online")

    def clean_duracion_sesion(self):
        return self.cleaned_data.get("duracion_sesion") or (self.instance.duracion_sesion if self.instance.pk else 60)


class PatientProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = ["telefono", "biografia"]
        widgets = {"biografia": forms.Textarea(attrs={"rows": 4})}


class AppointmentCreateForm(forms.ModelForm):
    start_at = forms.DateTimeField(label="Inicio", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    end_at = forms.DateTimeField(label="Fin", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    class Meta:
        model = Appointment
        fields = ["doctor", "start_at", "end_at", "modalidad", "notes"]
        labels = {"doctor": "Psicólogo", "modalidad": "Modalidad", "notes": "Motivo de consulta"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Cuéntanos brevemente el motivo de tu consulta"})}


class DoctorAvailabilityForm(forms.ModelForm):
    class Meta:
        model = DoctorAvailability
        fields = ["weekday", "start_time", "end_time", "active"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }
