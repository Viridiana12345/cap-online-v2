"""Django settings for CAP Online.
Local-first defaults with production-safe overrides for Render.
"""
from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env(path):
    """Carga .env en desarrollo sin sobrescribir variables definidas por Render."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env(BASE_DIR / ".env")
IS_RENDER = bool(os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"))
DEBUG = os.environ.get("DEBUG", "False" if IS_RENDER else "True").strip().lower() == "true"
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-cap-online-change-in-production"
    else:
        raise RuntimeError("SECRET_KEY is required in production.")


def _env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]

ALLOWED_HOSTS = _env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1],10.36.189.58"
)
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS", "https://cap-online.onrender.com")
if RENDER_EXTERNAL_HOSTNAME:
    origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "portal.middleware.DevMobileCorsMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cap_online.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "portal.context_processors.portal_roles",
    ]},
}]
WSGI_APPLICATION = "cap_online.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.config(default=DATABASE_URL, conn_max_age=600, ssl_require=not DEBUG)}
else:
    if not DEBUG:
        raise RuntimeError("DATABASE_URL is required in production.")
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Monterrey"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )},
}
MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "portal_dashboard"
LOGOUT_REDIRECT_URL = "landing"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

MOBILE_ALLOWED_ORIGINS = _env_list(
    "MOBILE_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,capacitor://localhost,http://localhost,https://localhost"
    if DEBUG else "",
)

# Correo seguro: las credenciales nunca deben guardarse en el repositorio.
# En local, si no hay credenciales, el enlace se imprime en la terminal.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com").strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").strip().lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").strip().lower() == "true"
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be True.")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "").strip()
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "CAP Online <no-reply@localhost>"
).strip()

# STUN funciona en muchas redes. Configura TURN para conexiones móviles,
# redes corporativas o NAT estricto donde una conexión directa no es posible.
WEBRTC_TURN_URL = os.environ.get("WEBRTC_TURN_URL", "").strip()
WEBRTC_TURN_USERNAME = os.environ.get("WEBRTC_TURN_USERNAME", "").strip()
WEBRTC_TURN_CREDENTIAL = os.environ.get("WEBRTC_TURN_CREDENTIAL", "").strip()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"portal": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
