import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction


class Command(BaseCommand):
    help = "Create an administrator only when explicitly enabled in the server environment."

    def handle(self, *args, **options):
        if os.environ.get("CAP_CREATE_ADMIN", "").strip().lower() != "true":
            self.stdout.write("Creacion inicial de administrador desactivada.")
            return
        username = os.environ.get("CAP_ADMIN_USERNAME", "").strip()
        email = os.environ.get("CAP_ADMIN_EMAIL", "").strip()
        password = os.environ.get("CAP_ADMIN_PASSWORD", "")
        if not username:
            raise CommandError("Falta CAP_ADMIN_USERNAME.")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write("La cuenta ya existe. No se modificaron sus datos ni permisos.")
            return
        if not email or not password:
            raise CommandError("Falta CAP_ADMIN_EMAIL o CAP_ADMIN_PASSWORD.")
        user = User(username=username, email=email, is_staff=True, is_superuser=True)
        try:
            validate_email(email)
            user.full_clean(exclude=["password"])
            validate_password(password, user)
        except ValidationError:
            raise CommandError(
                "Datos no validos: revisa usuario, correo y una contrasena fuerte "
                "que cumpla los validadores del proyecto."
            ) from None
        with transaction.atomic():
            User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(
            "Administrador creado. Elimina CAP_ADMIN_PASSWORD y desactiva CAP_CREATE_ADMIN en Render."
        ))
