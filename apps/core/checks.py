"""Contrôles de configuration (python manage.py check [--deploy])."""

from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def public_web_base_url_check(app_configs, **kwargs):
    """Les QR imprimés encodent PUBLIC_WEB_BASE_URL : en production, une URL https publique."""
    url = urlparse(settings.PUBLIC_WEB_BASE_URL)
    host = (url.hostname or "").lower()
    if url.scheme != "https" or host in {"localhost", "127.0.0.1", "10.0.2.2"} or host.endswith(".local"):
        return [
            Warning(
                f"PUBLIC_WEB_BASE_URL vaut « {settings.PUBLIC_WEB_BASE_URL} ».",
                hint="Les QR imprimés pointeraient vers une adresse inutilisable : indiquez le domaine "
                "public du site en https avant toute impression.",
                id="core.W001",
            )
        ]
    return []
