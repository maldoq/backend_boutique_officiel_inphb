"""Format d'erreur unique C.5 pour chaque type d'erreur."""

import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.test import RequestFactory
from rest_framework import exceptions as drf_exc
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.core.exceptions import (
    ConflictError,
    GoneError,
    InsufficientStock,
    NotFoundError,
    ServiceUnavailableError,
)
from apps.core.views import server_error


def call_view_raising(exc):
    class RaisingView(APIView):
        # Un schéma d'authentification est nécessaire pour que DRF réponde 401 (et non 403).
        authentication_classes = [JWTAuthentication]
        permission_classes = [AllowAny]

        def get(self, request):
            raise exc

    return RaisingView.as_view()(RequestFactory().get("/api/v1/test/"))


def assert_error_format(response, status, code):
    assert response.status_code == status
    assert set(response.data) == {"error"}
    assert set(response.data["error"]) == {"code", "message", "details"}
    assert response.data["error"]["code"] == code
    assert response.data["error"]["message"]


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (NotFoundError("Produit introuvable."), 404, "not_found"),
        (NotFoundError("Ce QR code est inconnu.", code="qr_not_found"), 404, "qr_not_found"),
        (GoneError("Ce QR code n'est plus actif.", code="qr_inactive"), 410, "qr_inactive"),
        (
            ConflictError("Transition impossible.", code="invalid_status_transition"),
            409,
            "invalid_status_transition",
        ),
        (InsufficientStock("Stock insuffisant."), 409, "insufficient_stock"),
        (
            ServiceUnavailableError("Paiement non activé.", code="payment_not_configured"),
            503,
            "payment_not_configured",
        ),
        (drf_exc.NotAuthenticated(), 401, "not_authenticated"),
        (drf_exc.AuthenticationFailed(), 401, "authentication_failed"),
        (InvalidToken(), 401, "authentication_failed"),
        (drf_exc.PermissionDenied(), 403, "permission_denied"),
        (DjangoPermissionDenied(), 403, "permission_denied"),
        (Http404(), 404, "not_found"),
        (drf_exc.NotFound(), 404, "not_found"),
        (drf_exc.MethodNotAllowed("POST"), 405, "method_not_allowed"),
        (drf_exc.Throttled(wait=12.3), 429, "throttled"),
    ],
)
def test_format_erreur_unique(exc, status, code):
    assert_error_format(call_view_raising(exc), status, code)


def test_erreur_metier_conserve_les_details():
    details = {"items": [{"variant_id": 12, "requested": 3, "available": 2}]}
    response = call_view_raising(InsufficientStock("Stock insuffisant.", details=details))
    assert response.data["error"]["details"] == details


def test_validation_error_details_par_champ():
    response = call_view_raising(drf_exc.ValidationError({"phone": ["Numéro invalide."]}))
    assert_error_format(response, 400, "validation_error")
    assert response.data["error"]["details"] == {"phone": ["Numéro invalide."]}


def test_validation_error_sans_champ():
    response = call_view_raising(drf_exc.ValidationError(["Panier vide."]))
    assert_error_format(response, 400, "validation_error")
    assert response.data["error"]["details"] == {"non_field_errors": ["Panier vide."]}


def test_throttled_indique_le_delai():
    response = call_view_raising(drf_exc.Throttled(wait=12.3))
    assert response.data["error"]["details"] == {"retry_after": 13}


@pytest.mark.django_db
def test_hote_non_autorise_400_en_json(client):
    response = client.get("/api/v1/health/", HTTP_HOST="pirate.example")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_hote_non_autorise_hors_api_reste_en_html(client):
    response = client.get("/django-admin/", HTTP_HOST="pirate.example")
    assert response.status_code == 400
    assert "json" not in response["Content-Type"]


def test_erreur_500_api_en_json_sans_detail_technique():
    response = server_error(RequestFactory().get("/api/v1/orders/"))
    assert response.status_code == 500
    assert response["Content-Type"] == "application/json"
    assert b'"code": "server_error"' in response.content
    assert b"Traceback" not in response.content
