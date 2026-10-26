"""Contrôles de configuration (python manage.py check [--deploy])."""

from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Tags, Warning, register

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "10.0.2.2", "0.0.0.0"}


def is_public_https_url(url: str) -> bool:
    """URL publique utilisable dans un QR imprimé : https et hôte qui n'est pas local."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https" and bool(host) and host not in _LOCAL_HOSTS and not host.endswith(".local")
    )


@register(Tags.security, deploy=True)
def public_web_base_url_check(app_configs, **kwargs):
    """Les QR imprimés encodent PUBLIC_WEB_BASE_URL : en production, une URL https publique."""
    if not is_public_https_url(settings.PUBLIC_WEB_BASE_URL):
        return [
            Warning(
                f"PUBLIC_WEB_BASE_URL vaut « {settings.PUBLIC_WEB_BASE_URL} ».",
                hint="Les QR imprimés pointeraient vers une adresse inutilisable : indiquez le domaine "
                "public du site en https avant toute impression.",
                id="core.W001",
            )
        ]
    return []
