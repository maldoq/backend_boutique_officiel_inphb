"""API d'administration du stock : ajustements, historique, alertes."""

import pytest

from apps.audit.models import AuditLog
from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.core.models import SiteSettings
from apps.inventory.models import StockMovement

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/admin"


@pytest.fixture
def manager(admin_api_client):
    return admin_api_client("GESTIONNAIRE_CATALOGUE")


@pytest.fixture
def variant():
    return VariantFactory(size="M", stock_quantity=10, product__name="Polo")


def adjust(client, variant, **payload):
    return client.post(f"{ADMIN}/variants/{variant.pk}/stock-adjustments/", payload, format="json")


def test_ajustement_reponse_et_audit(manager, variant):
    response = adjust(
        manager, variant, new_quantity=2, reason="inventory_correction", note="Inventaire annuel"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["stock_quantity"] == 2 and body["availability"] == "low_stock"
    assert body["movement"]["delta"] == -8 and body["movement"]["reason_label"] == "Correction d'inventaire"
    assert body["movement"]["created_by"] == manager.user.email
    assert AuditLog.objects.get(action="stock.adjust").changes["stock_quantity"] == [10, 2]


def test_stock_negatif_refuse(manager, variant):
    response = adjust(manager, variant, delta=-11, reason="inventory_correction", note="Casse")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "insufficient_stock"
    assert error["details"]["items"] == [{"variant_id": variant.pk, "requested": 11, "available": 10}]
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 10


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "restock"},
        {"new_quantity": 5, "delta": 1, "reason": "restock"},
        {"delta": 1, "reason": "order_reserved"},
        {"delta": -1, "reason": "manual_adjustment"},
        {"new_quantity": 10, "reason": "restock"},
    ],
)
def test_ajustement_invalide_400(manager, variant, payload):
    response = adjust(manager, variant, **payload)
    assert response.status_code == 400 and response.json()["error"]["code"] == "validation_error"
    assert not StockMovement.objects.exists()


def test_variante_inconnue_404(manager):
    response = manager.post(
        f"{ADMIN}/variants/999999/stock-adjustments/", {"delta": 1, "reason": "restock"}, format="json"
    )
    assert response.status_code == 404


def test_historique_filtres(manager, variant):
    other = VariantFactory(size="L", stock_quantity=0)
    adjust(manager, variant, delta=5, reason="restock")
    adjust(manager, other, delta=3, reason="restock")
    adjust(manager, variant, delta=-1, reason="manual_adjustment", note="Échantillon")
    url = f"{ADMIN}/stock/movements/"
    everything = manager.get(url).json()
    assert everything["count"] == 3
    assert everything["results"][0]["note"] == "Échantillon"  # du plus récent au plus ancien
    assert manager.get(url, {"variant": variant.pk}).json()["count"] == 2
    assert manager.get(url, {"product": other.product_id}).json()["count"] == 1
    assert manager.get(url, {"reason": "manual_adjustment"}).json()["count"] == 1
    today = everything["results"][0]["created_at"][:10]
    assert manager.get(url, {"date_from": today, "date_to": today}).json()["count"] == 3
    assert manager.get(url, {"date_from": "2026-12-31", "date_to": "2026-01-01"}).status_code == 400
    assert manager.get(url, {"reason": "inconnu"}).status_code == 400


def test_alertes(manager):
    SiteSettings.load()
    low = VariantFactory(size="M", stock_quantity=2, product__name="Carnet")
    out = VariantFactory(size="L", stock_quantity=0, product__name="Mug")
    VariantFactory(size="S", stock_quantity=40)
    coming = ProductFactory(is_coming_soon=True, variants__stock=0).variants.get()
    body = manager.get(f"{ADMIN}/stock/alerts/").json()
    assert body["counts"] == {"low_stock": 1, "out_of_stock": 2}
    assert body["low_stock"][0] == {
        "variant_id": low.pk,
        "sku": low.sku,
        "label": "M",
        "product": {"id": low.product_id, "reference": low.product.reference, "name": "Carnet"},
        "stock_quantity": 2,
        "threshold": 3,
        "is_coming_soon": False,
    }
    flags = {row["variant_id"]: row["is_coming_soon"] for row in body["out_of_stock"]}
    assert flags == {out.pk: False, coming.pk: True}
