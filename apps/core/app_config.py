"""Configuration distante servie à l'application mobile et au site (GET /api/v1/app/config/).

core est la première application (C.2) : elle n'importe jamais les apps suivantes. Celles-ci
fournissent leurs sections via register_app_config_section() dans leur AppConfig.ready()
(ex. orders → points de retrait à l'étape 12, content → pages légales en Phase 2).
"""

from collections.abc import Callable
from typing import Any

from django.conf import settings

from .models import SiteSettings

PAYMENT_DISABLED_MESSAGE = (
    "Le paiement en ligne n’est pas encore activé. "
    "Votre commande sera enregistrée et validée par la Boutique."
)
SECTIONS = ("pickup_points", "legal_pages")

_section_providers: dict[str, Callable[[Any], list[dict]]] = {}


def register_app_config_section(name: str, provider: Callable[[Any], list[dict]]) -> None:
    """Déclare la fonction (request) -> liste qui alimente une section de la configuration."""
    if name not in SECTIONS:
        raise ValueError(f"Section inconnue : {name!r} (attendu : {', '.join(SECTIONS)}).")
    _section_providers[name] = provider


def _section(name: str, request) -> list[dict]:
    provider = _section_providers.get(name)
    return list(provider(request)) if provider else []


def online_payment_enabled() -> bool:
    return settings.PAYMENT_PROVIDER != "not_configured"


def build_app_config(request) -> dict:
    """Assemble la configuration : boutique, fonctionnalités, paiement, limites, points de retrait."""
    site = SiteSettings.load()
    payment_enabled = online_payment_enabled()
    return {
        "shop": {
            "name": site.shop_name,
            "slogan": site.slogan,
            "contact_phone": site.contact_phone,
            "contact_email": site.contact_email,
        },
        "currency": "XOF",
        "mobile": {
            "min_supported_version": settings.MOBILE_MIN_SUPPORTED_VERSION,
            "latest_version": settings.MOBILE_LATEST_VERSION,
        },
        "features": {
            "guest_checkout": True,
            "online_payment": payment_enabled,
            # Fonctionnalités de Phase 2, activées quand elles seront livrées.
            "customer_accounts": False,
            "delivery": False,
            "promo_codes": False,
        },
        "payment": {
            "enabled": payment_enabled,
            "message": "" if payment_enabled else PAYMENT_DISABLED_MESSAGE,
        },
        "limits": {
            "max_qty_per_line": settings.MAX_QTY_PER_LINE,
            "max_lines_per_order": settings.MAX_LINES_PER_ORDER,
        },
        "pickup_points": _section("pickup_points", request),
        "legal_pages": _section("legal_pages", request),
        "maintenance_mode": site.maintenance_mode,
    }
