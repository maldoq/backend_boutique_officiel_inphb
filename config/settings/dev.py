"""Développement local : DEBUG, e-mails affichés dans la console."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
