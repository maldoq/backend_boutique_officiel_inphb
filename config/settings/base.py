"""Réglages communs à tous les environnements, lus depuis les variables d'environnement (.env)."""

from datetime import timedelta
from pathlib import Path

import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
if (BASE_DIR / ".env").is_file():
    # Les variables déjà définies dans l'environnement restent prioritaires.
    environ.Env.read_env(BASE_DIR / ".env")

# --- Obligatoires (aucune valeur par défaut) ---
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False

DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL", default="django-admin/")
API_VERSION = "1.0.0"

# --- Applications (apps métier dans l'ordre de dépendance C.2) ---
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.catalog",
    "apps.inventory",
    "apps.boxes",
    "apps.tracking",
    "apps.orders",
    "apps.payments",
    "apps.notifications",
    "apps.analytics",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.VisitorHeaderMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
            ],
        },
    },
]

# --- Utilisateurs et mots de passe (C.7 : longueur minimale 10) ---
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Langue, fuseau ---
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Abidjan"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Fichiers statiques et médias ---
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024  # images de 5 Mo max (C.7) + marge multipart

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # JWT simplejwt + invalidation des jetons après changement de mot de passe
        "apps.accounts.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],  # refus par défaut
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    # Nombre de proxys de confiance devant Django (X-Forwarded-For) : 0 en local, 1 derrière Nginx.
    "NUM_PROXIES": env.int("DJANGO_NUM_PROXIES", default=0),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Par IP : sur le campus, de nombreux visiteurs partagent la même IP publique (NAT, Wi-Fi).
        "anon": env("THROTTLE_ANON", default="2000/min"),
        "user": "1000/min",
        "login": "5/min",
        # Scan de QR : par visiteur (IP + identifiant de visite) et plafond large par IP.
        "qr_resolve": env("THROTTLE_QR_RESOLVE", default="30/min"),
        "qr_resolve_ip": env("THROTTLE_QR_RESOLVE_IP", default="600/min"),
        "tracking": "120/min",
        "order_create": "10/min",
        "order_lookup": "10/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    # last_login est mis à jour par apps.accounts.services.login_staff (connexion réelle uniquement).
}

# --- CORS (navigateur Angular ; le mobile n'est pas concerné) ---
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_HEADERS = (
    *default_headers,
    "idempotency-key",
    "x-visitor-id",
    "x-client-platform",
    "x-app-version",
)
CORS_EXPOSE_HEADERS = ["X-Visitor-Id"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- Documentation OpenAPI (accès libre ; restreint au personnel dans prod.py) ---
SPECTACULAR_SETTINGS = {
    "TITLE": "API Boutique INP-HB",
    "DESCRIPTION": "API unique du site web Angular, de l'admin Angular et de l'application Flutter.",
    "VERSION": API_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
}

# --- E-mails ---
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="boutique@exemple.ci")

# --- Journalisation (console ; format JSON en production) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Règles métier (lues depuis l'environnement) ---
MAX_QTY_PER_LINE = env.int("MAX_QTY_PER_LINE", default=10)
MAX_LINES_PER_ORDER = env.int("MAX_LINES_PER_ORDER", default=30)
STOCK_POLICY = env("STOCK_POLICY", default="reserve_on_order")
QR_CODE_LENGTH = env.int("QR_CODE_LENGTH", default=10)
QR_SCAN_DEDUP_SECONDS = env.int("QR_SCAN_DEDUP_SECONDS", default=10)
TRACKING_RETENTION_DAYS = env.int("TRACKING_RETENTION_DAYS", default=730)
DEFAULT_LOW_STOCK_THRESHOLD = env.int("DEFAULT_LOW_STOCK_THRESHOLD", default=3)

PUBLIC_WEB_BASE_URL = env("PUBLIC_WEB_BASE_URL").rstrip("/")
API_PUBLIC_BASE_URL = env("API_PUBLIC_BASE_URL").rstrip("/")

MOBILE_MIN_SUPPORTED_VERSION = env("MOBILE_MIN_SUPPORTED_VERSION", default="1.0.0")
MOBILE_LATEST_VERSION = env("MOBILE_LATEST_VERSION", default="1.0.0")

PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="not_configured")
SMS_PROVIDER = env("SMS_PROVIDER", default="not_configured")
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="not_configured")
