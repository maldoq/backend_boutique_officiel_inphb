"""API d'administration des boxes et QR codes (étape 10)."""

import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.capabilities import ROLE_CAPABILITIES, ROLES
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QRCode
from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.tests.factories import ProductFactory
from apps.tracking.models import TrackingEvent

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/admin"
QR_KEYS = {
    "id",
    "code",
    "is_active",
    "public_url",
    "image_png_url",
    "image_svg_url",
    "box",
    "product",
    "note",
    "replaced_by",
    "scans_count",
    "last_scanned_at",
    "activated_at",
    "deactivated_at",
    "created_by",
    "created_at",
}


@pytest.fixture
def marketing(admin_api_client):
    return admin_api_client("MARKETING")


def error(response):
    return response.json()["error"]


def scan(api_client, qr, visitor=None):
    return api_client.get(f"/api/v1/qr/{qr.code}/resolve/", HTTP_X_VISITOR_ID=visitor or str(uuid.uuid4()))


def path_of(url):
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


# --- Permissions --------------------------------------------------------------------------

ROUTES = [
    ("get", "/boxes/", "boxes.view"),
    ("post", "/boxes/", "boxes.manage"),
    ("get", "/boxes/{box}/", "boxes.view"),
    ("patch", "/boxes/{box}/", "boxes.manage"),
    ("delete", "/boxes/{box}/", "boxes.manage"),
    ("get", "/boxes/{box}/qr-codes/", "boxes.view"),
    ("get", "/qr-codes/", "boxes.view"),
    ("post", "/qr-codes/", "boxes.manage"),
    ("get", "/qr-codes/{qr}/", "boxes.view"),
    ("post", "/qr-codes/{qr}/deactivate/", "boxes.manage"),
    ("post", "/qr-codes/{qr}/activate/", "boxes.manage"),
    ("post", "/qr-codes/{qr}/regenerate/", "boxes.manage"),
    ("post", "/qr-codes/{qr}/reassign/", "boxes.manage"),
    ("get", "/qr-codes/{qr}/history/", "boxes.view"),
    ("get", "/qr-codes/{qr}/image/", "boxes.view"),
]


def _url(template):
    qr = QRCodeFactory()
    return ADMIN + template.format(box=qr.box.pk, qr=qr.pk)


@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize(("method", "template", "capability"), ROUTES)
def test_matrice_des_permissions(admin_api_client, role, method, template, capability):
    response = getattr(admin_api_client(role), method)(_url(template), {}, format="json")
    if capability in ROLE_CAPABILITIES[role]:
        assert response.status_code != 403, response.content
    else:
        assert response.status_code == 403


@pytest.mark.parametrize(("method", "template", "capability"), ROUTES)
def test_anonyme_401(api_client, method, template, capability):
    assert getattr(api_client, method)(_url(template), {}, format="json").status_code == 401


# --- Boxes ---------------------------------------------------------------------------------


def test_boxes_creation_liste_et_modification(marketing):
    created = marketing.post(
        f"{ADMIN}/boxes/",
        {"code": "box centre 01", "label": "Box Hall Centre", "site": "Centre"},
        format="json",
    )
    assert created.status_code == 201 and created.json()["code"] == "BOX-CENTRE-01"
    box = Box.objects.get()
    QRCodeFactory(box=box, product__name="Polo")
    QRCodeFactory(box=box, product__name="Mug", is_active=False)
    BoxFactory(site="ESA", is_active=False)
    listing = marketing.get(f"{ADMIN}/boxes/", {"site": "centre"}).json()["results"]
    assert [b["code"] for b in listing] == ["BOX-CENTRE-01"]
    assert (listing[0]["active_qr_count"], listing[0]["qr_count"]) == (1, 2)
    assert [p["name"] for p in listing[0]["products"]] == ["Polo"]
    assert marketing.get(f"{ADMIN}/boxes/", {"is_active": "false"}).json()["count"] == 1
    patched = marketing.patch(f"{ADMIN}/boxes/{box.pk}/", {"is_active": False}, format="json")
    assert patched.json()["is_active"] is False
    assert AuditLog.objects.get(action="box.deactivate").changes == {"is_active": [True, False]}
    assert (
        marketing.post(
            f"{ADMIN}/boxes/", {"code": "CENTRE", "label": "x", "site": "x"}, format="json"
        ).status_code
        == 400
    )


def test_suppression_de_box(marketing, api_client):
    empty = BoxFactory()
    assert marketing.delete(f"{ADMIN}/boxes/{empty.pk}/").status_code == 204
    with_qr = QRCodeFactory().box
    response = marketing.delete(f"{ADMIN}/boxes/{with_qr.pk}/")
    assert response.status_code == 409 and error(response)["code"] == "resource_in_use"
    with_scans = BoxFactory()
    TrackingEvent.objects.create(event_type="qr_scan", visitor_id=uuid.uuid4(), box=with_scans)
    assert marketing.delete(f"{ADMIN}/boxes/{with_scans.pk}/").status_code == 409


# --- QR codes ---------------------------------------------------------------------------------


def test_creation_conforme_au_contrat_et_doublon(marketing):
    box, product = BoxFactory(code="BOX-ESA-01"), ProductFactory(name="Polo INP-HB Vert")
    response = marketing.post(
        f"{ADMIN}/qr-codes/",
        {"box_id": box.pk, "product_id": product.pk, "note": "Vitrine ESA – étagère haute"},
        format="json",
    )
    assert response.status_code == 201
    data = response.json()
    assert set(data) == QR_KEYS
    assert data["public_url"] == f"https://boutique.test/q/{data['code']}"
    assert data["box"] == {"id": box.pk, "code": "BOX-ESA-01", "label": box.label, "site": box.site}
    assert data["product"] == {"id": product.pk, "slug": "polo-inp-hb-vert", "name": "Polo INP-HB Vert"}
    assert (data["replaced_by"], data["scans_count"], data["created_by"]) == (None, 0, marketing.user.email)
    assert "format=png" in data["image_png_url"] and "sig=" in data["image_png_url"]
    duplicate = marketing.post(
        f"{ADMIN}/qr-codes/", {"box_id": box.pk, "product_id": product.pk}, format="json"
    )
    assert duplicate.status_code == 409 and error(duplicate)["code"] == "qr_conflict"


def test_desactivation_regeneration_et_resolution_publique(marketing, api_client):
    qr = QRCodeFactory()
    base = f"{ADMIN}/qr-codes/{qr.pk}"
    assert marketing.post(f"{base}/deactivate/").json()["is_active"] is False
    assert scan(api_client, qr).status_code == 410
    assert marketing.post(f"{base}/activate/").json()["is_active"] is True
    regenerated = marketing.post(f"{base}/regenerate/")
    assert regenerated.status_code == 201
    new = regenerated.json()
    assert new["code"] != qr.code
    assert marketing.get(f"{base}/").json()["replaced_by"] == {"id": new["id"], "code": new["code"]}
    assert scan(api_client, qr).status_code == 410  # ancien code
    assert scan(api_client, QRCode.objects.get(pk=new["id"])).status_code == 200


def test_reaffectation_meme_code_historique_inchange(marketing, api_client):
    qr = QRCodeFactory(box__code="BOX-CENTRE-01")
    scan(api_client, qr)
    other = BoxFactory(code="BOX-ESTP-01")
    response = marketing.post(f"{ADMIN}/qr-codes/{qr.pk}/reassign/", {"box_id": other.pk}, format="json")
    assert response.status_code == 200
    assert (response.json()["code"], response.json()["box"]["code"]) == (qr.code, "BOX-ESTP-01")
    assert TrackingEvent.objects.get().box.code == "BOX-CENTRE-01"
    empty = marketing.post(f"{ADMIN}/qr-codes/{qr.pk}/reassign/", {}, format="json")
    assert empty.status_code == 400


def test_historique_chaine_et_audit(marketing, api_client):
    qr = QRCodeFactory()
    scan(api_client, qr)
    second = marketing.post(f"{ADMIN}/qr-codes/{qr.pk}/regenerate/").json()
    third = marketing.post(f"{ADMIN}/qr-codes/{second['id']}/regenerate/").json()
    history = marketing.get(f"{ADMIN}/qr-codes/{second['id']}/history/").json()
    assert history["predecessors"] == [{"id": qr.pk, "code": qr.code}]
    assert history["successors"] == [{"id": third["id"], "code": third["code"]}]
    assert [entry["action"] for entry in history["entries"]] == ["qr.regenerate", "qr.create"]
    first_history = marketing.get(f"{ADMIN}/qr-codes/{qr.pk}/history/").json()
    assert first_history["scans_count"] == 1
    assert [s["code"] for s in first_history["successors"]] == [second["code"], third["code"]]


def test_liste_filtres_scans_et_qr_d_une_box(marketing, api_client):
    box = BoxFactory()
    active = QRCodeFactory(box=box, product__name="Carnet")
    inactive = QRCodeFactory(box=box, product__name="Mug", is_active=False)
    QRCodeFactory(product__name="Stylo")
    scan(api_client, active)
    scan(api_client, active)
    by_box = marketing.get(f"{ADMIN}/boxes/{box.pk}/qr-codes/").json()
    assert {q["id"] for q in by_box} == {active.pk, inactive.pk}
    item = marketing.get(f"{ADMIN}/qr-codes/{active.pk}/").json()
    assert item["scans_count"] == 2 and item["last_scanned_at"]
    assert marketing.get(f"{ADMIN}/qr-codes/", {"box": box.pk, "is_active": "true"}).json()["count"] == 1
    assert marketing.get(f"{ADMIN}/qr-codes/", {"search": active.code.lower()}).json()["count"] == 1
    assert marketing.get(f"{ADMIN}/qr-codes/", {"search": "mug"}).json()["count"] == 1
    assert marketing.delete(f"{ADMIN}/qr-codes/{active.pk}/").status_code == 405  # on désactive


# --- Images ------------------------------------------------------------------------------------


def test_image_avec_jeton(marketing):
    qr = QRCodeFactory(box__code="BOX-CENTRE-01", product__name="Polo INP-HB Vert")
    png = marketing.get(f"{ADMIN}/qr-codes/{qr.pk}/image/", {"format": "png", "size": 300, "caption": "1"})
    assert png.status_code == 200 and png["Content-Type"] == "image/png"
    assert png["Content-Disposition"] == 'attachment; filename="QR-BOX-CENTRE-01-polo-inp-hb-vert.png"'
    svg = marketing.get(f"{ADMIN}/qr-codes/{qr.pk}/image/", {"format": "svg"})
    assert svg["Content-Type"] == "image/svg+xml" and svg.content.startswith(b"<?xml")


def test_lien_signe_utilisable_sans_jeton_puis_expire(marketing, api_client):
    qr = QRCodeFactory()
    links = marketing.get(f"{ADMIN}/qr-codes/{qr.pk}/").json()
    assert api_client.get(path_of(links["image_png_url"])).status_code == 200  # <img src> sans JWT
    assert api_client.get(path_of(links["image_svg_url"])).status_code == 200
    tampered = path_of(links["image_png_url"]).replace("format=png", "format=svg")
    assert api_client.get(tampered).status_code == 403  # signature liée au format
    with freeze_time(timezone.now() + timedelta(minutes=11)):
        expired = api_client.get(path_of(links["image_png_url"]))
    assert expired.status_code == 403 and error(expired)["code"] == "link_expired"


@pytest.mark.parametrize(
    "params", [{"format": "gif"}, {"size": 50}, {"size": 5000}, {"caption": "peut-etre"}]
)
def test_parametres_d_image_invalides(marketing, params):
    response = marketing.get(f"{ADMIN}/qr-codes/{QRCodeFactory().pk}/image/", params)
    assert response.status_code == 400 and error(response)["code"] == "validation_error"


def test_image_d_un_qr_inactif_refusee(marketing):
    response = marketing.get(f"{ADMIN}/qr-codes/{QRCodeFactory(is_active=False).pk}/image/")
    assert response.status_code == 409 and error(response)["code"] == "qr_inactive"


@override_settings(DEBUG=False, PUBLIC_WEB_BASE_URL="http://localhost:4200")
def test_image_refusee_sans_domaine_public(marketing):
    response = marketing.get(f"{ADMIN}/qr-codes/{QRCodeFactory().pk}/image/")
    assert response.status_code == 503 and error(response)["code"] == "public_url_not_configured"


def test_liens_de_telechargement_dans_django_admin(client, make_staff):
    client.force_login(make_staff(is_superuser=True))
    qr = QRCodeFactory()
    page = client.get(f"/django-admin/boxes/qrcode/{qr.pk}/change/").content.decode()
    assert "Télécharger PNG" in page and "Télécharger SVG" in page
