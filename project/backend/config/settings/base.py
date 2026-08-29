"""
Base settings for Bhagya Laxmi Library project.
"""
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR = backend/ (this file lives at backend/config/settings/base.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# The frontend/ folder (templates + static source) lives alongside backend/
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# Initialize environment variables
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    TOTAL_LIBRARY_SEATS=(int, 150),
    SEAT_MONTHLY_FEE=(int, 800),
    GRACE_PERIOD_HOURS=(int, 48),
    RENEWAL_REMINDER_DAYS=(list, [4, 3]),
    SEAT_HOLD_DURATION_MINUTES=(int, 30),
)

# Read .env file if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# Security
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-default-change-me-in-production")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Admin seed credentials (used by `manage.py seed_admin`; see apps/admin_portal login check)
ADMIN_EMAIL = env("ADMIN_EMAIL", default="")
ADMIN_PASSWORD = env("ADMIN_PASSWORD", default="")
ADMIN_PHONE_NUMBER = env("ADMIN_PHONE_NUMBER", default="0000000000")

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_htmx",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.seats",
    "apps.bookings",
    "apps.payments",
    "apps.complaints",
    "apps.notifications",
    "apps.audit",
    "apps.admin_portal",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database configuration
# Uses PostgreSQL by default or DATABASE_URL from environment
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    FRONTEND_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Business Constants (Bhagya Laxmi Library)
TOTAL_LIBRARY_SEATS = env("TOTAL_LIBRARY_SEATS")
SEAT_MONTHLY_FEE = env("SEAT_MONTHLY_FEE")
GRACE_PERIOD_HOURS = env("GRACE_PERIOD_HOURS")
RENEWAL_REMINDER_DAYS = env.list("RENEWAL_REMINDER_DAYS", default=[4, 3], cast=int)
SEAT_HOLD_DURATION_MINUTES = env("SEAT_HOLD_DURATION_MINUTES")

# Authentication URL Redirects
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "portal:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

# Email / SMTP Configuration
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Bhagya Laxmi Library <noreply@bhagyalaxmilibrary.com>",
)

# Safe console backend fallback for local development if SMTP credentials are empty
if not EMAIL_HOST_USER and DEBUG and "EMAIL_BACKEND" not in env:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Google OAuth 2.0 Configuration
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")
GOOGLE_REDIRECT_URI = env("GOOGLE_REDIRECT_URI", default="")

# Celery & Redis Configuration
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://127.0.0.1:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60