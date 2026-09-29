INSTRUCCIONES RAPIDAS

1) Usar Python 3.12 o posterior compatible con Django 6.0 y un entorno virtual.
   Instalar las dependencias de requirements.txt.
2) Configurar en PowerShell, solo para desarrollo local:
   $env:DEBUG = "True"
   $env:EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
   Quitar DATABASE_URL de esta sesión si apunta a un servidor remoto.
   Sin DATABASE_URL y con DEBUG=True se utiliza db.sqlite3 local.
   No se cargan archivos .env automáticamente.
3) Ejecutar (migrate modifica únicamente la base configurada; revisarla antes):
   python manage.py migrate
   python manage.py runserver

4) Registrar psicologos desde RH:
   /portal/rh/doctores/nuevo/

IMPORTANTE:
- El login usa correo como username.
- Para doctores creados en RH, el sistema guarda username=email automaticamente.
- Si quieres entrar al admin, crea un superusuario con:
  python manage.py createsuperuser

CONFIGURACIÓN DE PRODUCCIÓN (RENDER)

- DEBUG es False por defecto. Mantenerlo en False en Render.
- SECRET_KEY es obligatoria con DEBUG=False; conservar la clave segura existente.
  No se permite la clave de respaldo de desarrollo en producción.
- DATABASE_URL es obligatoria con DEBUG=False. La conexión mantiene SSL.
  Estos cambios no ejecutan migraciones ni modifican Render por sí mismos.
- ALLOWED_HOSTS: lista separada por comas, sin esquema ni rutas.
  Predeterminado en producción: cap-online.onrender.com.
  En desarrollo: localhost,127.0.0.1,[::1]. Añadir IPs de LAN explícitamente si se usan.
- CSRF_TRUSTED_ORIGINS: lista separada por comas de orígenes completos.
  Predeterminado: https://cap-online.onrender.com.
- RENDER_EXTERNAL_HOSTNAME se incorpora a hosts y a orígenes HTTPS sin duplicados.
- Se conserva la configuración SMTP existente; requiere credenciales para enviar correo.
- Los estáticos usan STORAGES y WhiteNoise. collectstatic genera staticfiles/.
  La carpeta opcional static/ solo se registra si existe.
- MEDIA_ROOT y MEDIA_URL pueden configurarse por entorno; por defecto media/ y /media/.
  No se trasladan archivos existentes. En producción se debe verificar almacenamiento
  persistente y servicio de multimedia separado: WhiteNoise no sirve archivos subidos.
  Las rutas multimedia de desarrollo siguen disponibles únicamente con DEBUG=True.
- Revisar HTTPS/HSTS con la configuración real del proxy antes de habilitarlo.
- La ruta /crear-admin/ fue retirada. Si se usó, revisar y cambiar la contraseña
  de esa cuenta mediante administración autorizada; no se alteran cuentas existentes.

PLANTILLAS INACTIVAS IDENTIFICADAS (CONSERVADAS)

- portal/templates/registration/: el flujo configurado usa portal/auth/ y auth/.
- portal/templates/portal/calendar.html: la vista redirige a calendarios por rol.
- portal/templates/portal/calls.html y call_room.html: rutas deshabilitadas.
  calls.html conserva un error de etiquetas de plantilla previamente detectado.
- portal/templates.zip: archivo histórico, no utilizado por el motor de plantillas.

COMPROBACIONES LOCALES

- python manage.py check
- python manage.py test portal
- python manage.py makemigrations --check --dry-run
Antes de estos comandos, verificar que DATABASE_URL no apunte a Render.
Las pruebas usan una base de pruebas; nunca ejecutarlas contra credenciales de producción.
