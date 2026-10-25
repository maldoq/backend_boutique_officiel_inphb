"""Tests : hachage rapide, médias temporaires, throttling désactivé.

Fonctionne sans fichier .env (CI). Pour les tests de concurrence sur le stock,
fournir un DATABASE_URL PostgreSQL dans l'environnement.
"""

import os
import tempfile

# Valeurs fictives utilisées seulement si l'environnement ne les fournit pas.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
os.environ.setdefault("PUBLIC_WEB_BASE_URL", "http://boutique.test")
os.environ.setdefault("API_PUBLIC_BASE_URL", "http://testserver")

from .base import *  # noqa: E402, F403
from .base import REST_FRAMEWORK  # noqa: E402

DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="boutique-test-media-")
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Throttling désactivé : un taux None laisse passer toutes les requêtes.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {scope: None for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]},
}
