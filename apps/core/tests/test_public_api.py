"""Routes publiques du socle : /health/, /app/config/, route inconnue."""

from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import override_settings

from apps.core import app_config
from apps.core.models import SiteSettings


@pytest.mark.django_db
def test_health_ok(api_client):
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["version"] == "1.0.0"
    assert data["time"].endswith("Z")
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_health_base_indisponible(api_client):
    with mock.patch("apps.core.views.connection.cursor", side_effect=DatabaseError("down")):
        response = api_client.get("/api/v1/health/")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "error"


@pytest.mark.django_db
def test_health_ignore_un_jeton_invalide(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")
    assert api_client.get("/api/v1/health/").status_code == 200


@pytest.mark.django_db
def test_app_config_contenu(api_client):
    response = api_client.get("/api/v1/app/config/")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "shop",
        "currency",
        "mobile",
        "features",
        "payment",
        "limits",
        "pickup_points",
        "legal_pages",
        "maintenance_mode",
    }
    assert data["shop"]["name"] == "Boutique INP-HB"
    assert data["currency"] == "XOF"
    assert data["mobile"] == {"min_supported_version": "1.0.0", "latest_version": "1.0.0"}
    assert data["features"]["guest_checkout"] is True
    assert data["features"]["online_payment"] is False
    assert data["payment"]["enabled"] is False
    assert "pas encore activé" in data["payment"]["message"]
    assert data["limits"] == {"max_qty_per_line": 10, "max_lines_per_order": 30}
    assert data["pickup_points"] == []
    assert data["legal_pages"] == []
    assert data["maintenance_mode"] is False


@pytest.mark.django_db
def test_app_config_reflete_les_parametres(api_client):
    site = SiteSettings.load()
    site.maintenance_mode = True
    site.contact_email = "boutique@exemple.ci"
    site.save()
    data = api_client.get("/api/v1/app/config/").json()
    assert data["maintenance_mode"] is True
    assert data["shop"]["contact_email"] == "boutique@exemple.ci"


@pytest.mark.django_db
@override_settings(PAYMENT_PROVIDER="wave")
def test_app_config_paiement_active_si_fournisseur_configure(api_client):
    data = api_client.get("/api/v1/app/config/").json()
    assert data["payment"] == {"enabled": True, "message": ""}
    assert data["features"]["online_payment"] is True


@pytest.mark.django_db
def test_app_config_section_fournie_par_une_autre_app(api_client, monkeypatch):
    monkeypatch.setattr(app_config, "_section_providers", {})
    point = {
        "id": 1,
        "code": "BOUTIQUE-CENTRE",
        "name": "Boutique INP-HB Centre",
        "address": "Campus Centre, Yamoussoukro",
        "opening_hours": "Lun–Ven 8h–17h",
    }
    app_config.register_app_config_section("pickup_points", lambda request: [point])
    assert api_client.get("/api/v1/app/config/").json()["pickup_points"] == [point]


def test_section_inconnue_refusee():
    with pytest.raises(ValueError):
        app_config.register_app_config_section("inconnue", lambda request: [])


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/v1/inexistant/", "/api/v1/admin/inexistant/", "/api/v1/x/y/z"])
def test_route_inconnue_format_c5(api_client, path):
    response = api_client.get(path)
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Ressource introuvable.", "details": {}}
    }


@pytest.mark.django_db
def test_routes_publiques_documentees(api_client):
    schema = api_client.get("/api/schema/").content.decode()
    assert "/api/v1/health/" in schema
    assert "/api/v1/app/config/" in schema
