"""Django settings for local development and production deployment.

Production values are supplied through environment variables.  Copy
``.env.example`` to ``.env`` for a local setup, or configure the same
variables in the deployment platform's secret/configuration store.
"""

from pathlib import Path
from urllib.parse import urlparse
import os

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")
elif (BASE_DIR / ".env").exists():
    # Keep local setup usable even before the optional dotenv package is
    # installed; deployment platforms should provide environment variables
    # directly and will take precedence via setdefault.
    for raw_line in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'").strip())


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_int(name, default):
    value = os.getenv(name)
    return int(value) if value else default


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "local-development-only-insecure-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    "https://ddsnk.pythonanywhere.com",
).strip().rstrip("/")

app_origin = urlparse(
    APP_BASE_URL if "://" in APP_BASE_URL else f"https://{APP_BASE_URL}"
)

default_hosts = ["ddsnk.pythonanywhere.com"]

if app_origin.hostname and app_origin.hostname not in default_hosts:
    default_hosts.append(app_origin.hostname)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ",".join(default_hosts),
)

if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must contain at least one host in production."
    )

csrf_origins = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if not DEBUG and app_origin.scheme and app_origin.hostname:
    configured_origin = f"{app_origin.scheme}://{app_origin.netloc}"
    if configured_origin not in csrf_origins:
        csrf_origins.append(configured_origin)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "notifications.apps.NotificationsConfig",
    "hr_app.HRapp.apps.HrappConfig",
    "hr_app.appraisals.apps.AppraisalsConfig",
    "meal_app.meal.apps.MealConfig",
    "procure_app.procurement.apps.ProcurementConfig",
    "vsla_app.vsla.apps.VslaConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.UserTypeModuleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LastSeenMiddleware",
]

# WhiteNoise serves collected static files in deployment. Keep local
# runserver usable before deployment dependencies have been installed.
try:
    import whitenoise  # noqa: F401
except ImportError:
    pass
else:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.portal_context",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    try:
        import dj_database_url
    except ImportError as exc:
        raise ImproperlyConfigured("Install dj-database-url when DATABASE_URL is configured.") from exc
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=env_int("DJANGO_DB_CONN_MAX_AGE", 600),
            conn_health_checks=True,
        )
    }
else:
    if not DEBUG and not env_bool("DJANGO_ALLOW_SQLITE", False):
        raise ImproperlyConfigured(
            "DATABASE_URL must be set for production. Set DJANGO_ALLOW_SQLITE=true only for a deliberate single-server deployment."
        )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Africa/Kampala")
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
    "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
},
    # "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/portal/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
PASSWORD_RESET_TIMEOUT = env_int("DJANGO_PASSWORD_RESET_TIMEOUT", 3600)
AUTHENTICATION_BACKENDS = ["core.backends.StaffProfileBackend"]
AUTH_USER_MODEL = "core.StaffProfile"


# Email is console-based locally and SMTP-based only when production settings
# are explicitly provided. No credentials are stored in source control.
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 20)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "DDS-NK THRIVE <no-reply@example.com>")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[DDS-NK THRIVE] ")


# HTTPS and cookie protections are enabled automatically outside development.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = env_bool("DJANGO_CSRF_COOKIE_HTTPONLY", False)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
CSRF_TRUSTED_ORIGINS = csrf_origins

DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env_int("DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
