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


def _payload(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": details or {}}}


def api_exception_handler(exc, context):
    """Renvoie toutes les erreurs au format unique {"error": {code, message, details}} (C.5)."""
    if isinstance(exc, BusinessError):
        return Response(_payload(exc.code, exc.message, exc.details), status=exc.status_code)
    response = exception_handler(exc, context)
    if response is None:
        return None  # erreur 500 : journalisée par Django, aucun détail exposé
    if isinstance(exc, drf_exc.ValidationError):
        response.data = _payload("validation_error", "Certaines données sont invalides.", response.data)
    elif isinstance(exc, Http404):
        response.data = _payload("not_found", "Ressource introuvable.")
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else response.data
        code = getattr(exc, "default_code", "error")
        if isinstance(exc, drf_exc.Throttled):
            code = "throttled"
        response.data = _payload(code, str(detail))
    return response
