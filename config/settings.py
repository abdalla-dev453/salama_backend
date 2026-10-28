"""
SALAMA backend settings. Everything secret comes from environment variables
(see .env.example). Nothing sensitive is hard-coded.
"""
import base64
import hashlib
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "accounts",
    "cases",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database: PostgreSQL
# --------------------------------------------------------------------------
if env("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(env("DATABASE_URL"), conn_max_age=60)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "salama"),
            "USER": env("POSTGRES_USER", "salama"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

# Rate-limit counters live in the database so every gunicorn worker shares them
# (the default per-process cache would multiply every limit by the worker count).
# `python manage.py createcachetable` creates the table (docker/entrypoint.sh does it).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "salama_cache",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Throttle counters (login attempts, intake rate limits) are kept in the
# database so ALL gunicorn workers share them. Without this each worker would
# count separately and the limits would be several times too generous.
# `python manage.py createcachetable` creates the table (the Docker
# entrypoint does it for you).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "salama_cache",
    }
}

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/dashboard/"

# --------------------------------------------------------------------------
# i18n / static
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# REST framework + JWT
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "cases.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {
        # Rural mobile networks share IPs (carrier NAT), so keep intake generous.
        "intake": env("THROTTLE_INTAKE", "300/hour"),
        "login": env("THROTTLE_LOGIN", "20/min"),
        "sms_webhook": env("THROTTLE_SMS_WEBHOOK", "1000/hour"),
    },
    "NUM_PROXIES": int(env("NUM_PROXIES", "0")),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "7"))),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
}

# --------------------------------------------------------------------------
# SALAMA specific
# --------------------------------------------------------------------------
# Optional shared key the mobile app sends as "X-Salama-Key" on survivor
# submissions. It is NOT a secret (it ships inside the app); it only keeps
# casual bots away. Real protection = throttling + validation.
SURVIVOR_API_KEY = env("SURVIVOR_API_KEY", "")

# Africa's Talking incoming-SMS callback. The webhook is refused unless this
# token is set and matches ?token=... (or X-Webhook-Token header).
AT_WEBHOOK_TOKEN = env("AT_WEBHOOK_TOKEN", "")

# Optional: SMS CHWs when an SOS arrives (no personal data in the message).
AT_USERNAME = env("AT_USERNAME", "")
AT_API_KEY = env("AT_API_KEY", "")
AT_SENDER_ID = env("AT_SENDER_ID", "")
AT_SANDBOX = env_bool("AT_SANDBOX", False)
NOTIFY_CHWS_ON_SOS = env_bool("NOTIFY_CHWS_ON_SOS", False)

# Field-level encryption of sensitive text (description, phone numbers, notes,
# raw SMS). Comma separated Fernet keys; the FIRST encrypts, all can decrypt
# (so you can rotate keys). Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")
if not FIELD_ENCRYPTION_KEYS:
    if DEBUG:
        FIELD_ENCRYPTION_KEYS = [
            base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
        ]
    else:
        raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEYS")

# --------------------------------------------------------------------------
# Production hardening (HTTPS etc.)
# --------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]  # so Docker's health check works
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]  # container health checks use plain http
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --------------------------------------------------------------------------
# Logging (never log case content)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
