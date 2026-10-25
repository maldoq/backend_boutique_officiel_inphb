"""Production : HTTPS, HSTS, WhiteNoise, journaux JSON, documentation API réservée au personnel."""

from .base import *  # noqa: F403
from .base import LOGGING, MIDDLEWARE, REST_FRAMEWORK, SPECTACULAR_SETTINGS, env

DEBUG = False

# Derrière Nginx : l'IP client réelle (throttling) est lue dans X-Forwarded-For.
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": env.int("DJANGO_NUM_PROXIES", default=1)}

# --- HTTPS (derrière Nginx qui termine TLS) ---
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# preload engage durablement le domaine : à activer seulement sur décision de l'INP-HB.
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --- Fichiers statiques servis par WhiteNoise ---
MIDDLEWARE = [
    MIDDLEWARE[0],  # SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Documentation OpenAPI : personnel authentifié uniquement (C.7) ---
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
    "SERVE_AUTHENTICATION": [
        "rest_framework.authentication.SessionAuthentication",  # session Django Admin
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
}

# --- Journaux au format JSON (une ligne par événement) ---
LOGGING = {
    **LOGGING,
    "formatters": {"json": {"()": "config.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
}
