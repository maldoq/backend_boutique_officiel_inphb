import logging

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.utils import timezone
from django.views import defaults
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from .app_config import build_app_config
from .exceptions import error_payload
from .serializers import AppConfigSerializer, HealthSerializer
from .viewsets import PublicAPIView

logger = logging.getLogger(__name__)


class HealthView(PublicAPIView):
    """État du service et de la base (surveillance toutes les minutes)."""

    throttle_classes = []  # la sonde de surveillance ne doit jamais être limitée

    @extend_schema(
        tags=["Système"],
        summary="État du service",
        responses={200: HealthSerializer, 503: HealthSerializer},
    )
    def get(self, request):
        database = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            logger.exception("Health-check : base de données injoignable")
            database = "error"
        data = {
            "status": "ok" if database == "ok" else "degraded",
            "database": database,
            "version": settings.API_VERSION,
            "time": timezone.now().replace(microsecond=0),
        }
        response = Response(HealthSerializer(data).data, status=200 if database == "ok" else 503)
        response["Cache-Control"] = "no-store"
        return response


class AppConfigView(PublicAPIView):
    """Configuration distante : le mobile n'a rien à coder en dur (C.4)."""

    @extend_schema(tags=["Système"], summary="Configuration de l'application", responses=AppConfigSerializer)
    def get(self, request):
        response = Response(AppConfigSerializer(build_app_config(request)).data)
        response["Cache-Control"] = "public, max-age=60"
        return response


def _is_api_request(request) -> bool:
    return request.path.startswith("/api/")


def api_not_found(request, *args, **kwargs):
    """Route inconnue sous /api/v1/ : 404 au format C.5, y compris en DEBUG."""
    return JsonResponse(error_payload("not_found", "Ressource introuvable."), status=404)


def bad_request(request, exception=None):
    """handler400 (ex. en-tête Host non autorisé) : JSON pour l'API."""
    if _is_api_request(request):
        return JsonResponse(error_payload("bad_request", "Requête invalide."), status=400)
    return defaults.bad_request(request, exception)


def permission_denied(request, exception=None):
    """handler403 hors DRF (ex. CSRF) : JSON pour l'API."""
    if _is_api_request(request):
        return JsonResponse(error_payload("permission_denied", "Accès refusé."), status=403)
    return defaults.permission_denied(request, exception)


def page_not_found(request, exception=None):
    """handler404 : JSON pour l'API, page Django par défaut ailleurs (Django Admin…)."""
    if _is_api_request(request):
        return api_not_found(request)
    return defaults.page_not_found(request, exception)


def server_error(request):
    """handler500 : JSON sans détail technique pour l'API (l'erreur est journalisée par Django)."""
    if _is_api_request(request):
        return JsonResponse(
            error_payload("server_error", "Une erreur inattendue est survenue. Veuillez réessayer."),
            status=500,
        )
    return defaults.server_error(request)
