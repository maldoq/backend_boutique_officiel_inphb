"""Erreurs métier et format d'erreur unique de l'API (C.5) : {"error": {code, message, details}}."""

import math

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exc
from rest_framework.response import Response
from rest_framework.views import exception_handler


class BusinessError(Exception):
    status_code = 400
    code = "business_error"

    def __init__(self, message, *, code=None, details=None, status_code=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = details or {}
        self.status_code = status_code or self.status_code


class NotFoundError(BusinessError):
    status_code, code = 404, "not_found"


class ConflictError(BusinessError):
    status_code, code = 409, "conflict"


class GoneError(BusinessError):
    status_code, code = 410, "gone"


class ServiceUnavailableError(BusinessError):
    status_code, code = 503, "service_unavailable"


class InsufficientStock(ConflictError):
    code = "insufficient_stock"


def error_payload(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _detail_message_and_code(exc: drf_exc.APIException) -> tuple[str, str]:
    detail = exc.detail
    if isinstance(detail, dict):  # ex. simplejwt : {"detail": "...", "code": "token_not_valid", ...}
        return str(detail.get("detail", exc.default_detail)), str(detail.get("code", exc.default_code))
    if isinstance(detail, list):
        detail = detail[0] if detail else exc.default_detail
    return str(detail), getattr(detail, "code", None) or exc.default_code


def api_exception_handler(exc, context):
    """Gestionnaire DRF : toutes les erreurs gérées sortent au format C.5."""
    if isinstance(exc, BusinessError):
        return Response(error_payload(exc.code, exc.message, exc.details), status=exc.status_code)

    # Exceptions Django converties en équivalents DRF pour obtenir un code stable.
    if isinstance(exc, Http404):
        exc = drf_exc.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exc.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None  # erreur 500 : journalisée par Django, réponse JSON par core.views.server_error

    if isinstance(exc, drf_exc.ValidationError):
        details = response.data if isinstance(response.data, dict) else {"non_field_errors": response.data}
        response.data = error_payload("validation_error", "Certaines données sont invalides.", details)
    elif isinstance(exc, drf_exc.NotFound):
        response.data = error_payload("not_found", "Ressource introuvable.")
    elif isinstance(exc, drf_exc.Throttled):
        retry_after = math.ceil(exc.wait) if exc.wait is not None else None
        response.data = error_payload(
            "throttled",
            "Trop de requêtes. Veuillez réessayer dans quelques instants.",
            {"retry_after": retry_after} if retry_after is not None else None,
        )
    else:
        message, code = _detail_message_and_code(exc)
        if isinstance(exc, drf_exc.AuthenticationFailed):
            code = "authentication_failed"  # jeton expiré ou invalide (y compris simplejwt)
        response.data = error_payload(code, message)
    return response
