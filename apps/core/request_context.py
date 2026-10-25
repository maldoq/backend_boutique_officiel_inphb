"""Contexte client lu dans les en-têtes : visiteur anonyme, canal, version de l'application."""

import re
import uuid
from dataclasses import dataclass

from .choices import Channel

_APP_VERSION = re.compile(r"^\d{1,4}(\.\d{1,4}){0,3}$")


@dataclass(frozen=True)
class VisitorContext:
    visitor_id: uuid.UUID
    is_new: bool  # True si le serveur vient de générer l'identifiant


def _http_request(request):
    """Requête Django sous-jacente (une Request DRF l'enveloppe dans _request)."""
    return getattr(request, "_request", request)


def parse_visitor_id(value) -> uuid.UUID | None:
    """UUID v4 valide, sinon None."""
    if not value:
        return None
    try:
        parsed = uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        return None
    return parsed


def get_visitor_id(request) -> VisitorContext:
    """Identifiant de visite anonyme (R08) depuis X-Visitor-Id, ou nouveau UUID v4.

    L'identifiant retenu est mémorisé sur la requête : VisitorHeaderMiddleware le renvoie
    dans l'en-tête de réponse X-Visitor-Id pour que le client le conserve.
    """
    http_request = _http_request(request)
    cached = getattr(http_request, "visitor_context", None)
    if cached is not None:
        return cached
    parsed = parse_visitor_id(http_request.headers.get("X-Visitor-Id"))
    context = VisitorContext(visitor_id=parsed or uuid.uuid4(), is_new=parsed is None)
    http_request.visitor_context = context
    http_request.visitor_id = str(context.visitor_id)
    return context


def get_client_platform(request) -> str:
    """Canal client (web / android / ios), sinon unknown."""
    value = (_http_request(request).headers.get("X-Client-Platform") or "").strip().lower()
    return value if value in Channel.values and value != Channel.UNKNOWN else Channel.UNKNOWN


def get_app_version(request) -> str | None:
    """Version de l'application Flutter (X-App-Version), si elle est bien formée."""
    value = (_http_request(request).headers.get("X-App-Version") or "").strip()
    return value if _APP_VERSION.match(value) else None
