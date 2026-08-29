"""
Local development settings for Bhagya Laxmi Library.
"""
from .base import *  # noqa: F401, F403
from .base import env

DEBUG = True

# Email backend for development (outputs to console)
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")

# Static files storage in local dev (simple without manifest hashing for quick reloads)
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
