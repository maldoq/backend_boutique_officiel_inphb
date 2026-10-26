import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import ProductFactory
from apps.inventory.models import StockMovement

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, make_staff):
    admin = make_staff(email="root@exemple.ci", is_superuser=True)
    client.force_login(admin)
    client.admin = admin
    return client


@pytest.fixture
def variant():
    return ProductFactory(variants__stock=10).variants.get()


def adjust_url(variant):
    return reverse("admin:inventory_stock_adjust", args=[variant.pk])


def test_lien_ajuster_le_stock_dans_la_fiche_produit(staff_client, variant):
    response = staff_client.get(f"/django-admin/catalog/product/{variant.product_id}/change/")
    assert response.status_code == 200
    assert adjust_url(variant) in response.content.decode()


def test_ajustement_depuis_l_admin(staff_client, variant):
    assert staff_client.get(adjust_url(variant)).status_code == 200
    response = staff_client.post(adjust_url(variant), {"new_quantity": "25", "reason": "restock", "note": ""})
    assert response.status_code == 302
    assert response["Location"].endswith(f"/catalog/product/{variant.product_id}/change/")
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 25
    movement = StockMovement.objects.get()
    assert (movement.delta, movement.created_by) == (15, staff_client.admin)
    assert AuditLog.objects.filter(action="stock.adjust").count() == 1


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"delta": "-20", "reason": "inventory_correction", "note": "Inventaire"}, "Stock insuffisant"),
        ({"delta": "-2", "reason": "manual_adjustment", "note": ""}, "note est obligatoire"),
        ({"new_quantity": "10", "reason": "restock"}, "déjà de 10"),
    ],
)
def test_ajustement_refuse_avec_message(staff_client, variant, data, message):
    response = staff_client.post(adjust_url(variant), data)
    assert response.status_code == 200
    assert message in response.content.decode()
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 10
    assert not StockMovement.objects.exists()


def test_ajustement_reserve_aux_personnes_autorisees(client, make_staff, variant):
    client.force_login(make_staff("MARKETING"))  # staff sans permission Django sur les variantes
    assert client.get(adjust_url(variant)).status_code == 403


def test_historique_en_lecture_seule(staff_client, variant):
    staff_client.post(adjust_url(variant), {"delta": "5", "reason": "restock"})
    movement = StockMovement.objects.get()
    assert staff_client.get("/django-admin/inventory/stockmovement/").status_code == 200
    assert staff_client.get(f"/django-admin/inventory/stockmovement/{movement.pk}/change/").status_code == 200
    assert staff_client.get("/django-admin/inventory/stockmovement/add/").status_code == 403
    assert (
        staff_client.post(
            f"/django-admin/inventory/stockmovement/{movement.pk}/delete/", {"post": "yes"}
        ).status_code
        == 403
    )
