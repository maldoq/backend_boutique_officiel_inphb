"""Garanties en base des commandes (étape 12)."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.boxes.tests.factories import QRCodeFactory
from apps.catalog import services as catalog
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.orders.models import DeletionForbidden, Order, OrderItem, OrderStatusHistory, PickupPoint
from apps.orders.tests.factories import OrderFactory, PickupPointFactory, make_order

pytestmark = pytest.mark.django_db


def rejected(callable_):
    with pytest.raises(IntegrityError), transaction.atomic():
        callable_()


def update(order, **fields):
    return lambda: Order.objects.filter(pk=order.pk).update(**fields)


# --- Point de retrait initial (D09) ---------------------------------------------------------


def test_point_de_retrait_initial_sans_donnee_inventee():
    point = PickupPoint.objects.get(code="BOUTIQUE-CENTRE")
    assert (point.name, point.is_active) == ("Boutique INP-HB Centre", True)
    assert (point.address, point.opening_hours, point.phone) == ("", "", "")


def test_migration_du_point_de_retrait_relancable():
    migration = importlib.import_module("apps.orders.migrations.0002_initial_pickup_point")
    migration.create_pickup_point(django_apps, None)
    migration.create_pickup_point(django_apps, None)
    assert PickupPoint.objects.filter(code="BOUTIQUE-CENTRE").count() == 1


def test_point_de_retrait_normalise():
    point = PickupPoint(code=" point esa ", name="Point ESA", phone="07 00 00 00 00")
    point.full_clean()
    assert (point.code, point.phone) == ("POINT-ESA", "+2250700000000")


def test_point_de_retrait_utilise_non_supprimable():
    order = OrderFactory()
    with pytest.raises(ProtectedError):
        order.pickup_point.delete()


# --- Montants (R01, R15) --------------------------------------------------------------------------


def test_commande_coherente(make_staff):
    variant = VariantFactory(product__price_xof=12000, size="M")
    order = make_order([(variant, 2, None)])
    assert (order.subtotal_xof, order.total_xof, order.currency) == (24000, 24000, "XOF")
    assert (order.status, order.payment_status) == ("pending", "unpaid")
    assert (order.status_label, order.payment_status_label) == ("En attente de validation", "Non payée")
    assert isinstance(order.pk, type(order.id)) and len(str(order.pk)) == 36  # UUID


def test_contraintes_de_montant():
    order = make_order([(VariantFactory(), 1, None)])
    rejected(update(order, total_xof=order.total_xof + 1))
    rejected(update(order, discount_xof=order.subtotal_xof + 1, total_xof=0))
    rejected(update(order, currency="EUR"))
    item = order.items.get()
    rejected(lambda: OrderItem.objects.filter(pk=item.pk).update(line_total_xof=item.line_total_xof + 1))
    rejected(lambda: OrderItem.objects.filter(pk=item.pk).update(quantity=0, line_total_xof=0))
    rejected(lambda: OrderItem.objects.filter(pk=item.pk).update(unit_price_xof=0, line_total_xof=0))
    Order.objects.filter(pk=order.pk).update(
        discount_xof=1000, shipping_fee_xof=500, total_xof=order.subtotal_xof - 500
    )  # cohérent : accepté


# --- Statuts ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "inconnu"},
        {"payment_status": "gratuit"},
        {"status": "ready_for_pickup"},  # sans date « prête »
        {"status": "collected", "ready_at": timezone.now()},  # sans date de retrait
        {"status": "cancelled", "cancelled_at": timezone.now()},  # sans motif
        {"status": "cancelled", "cancellation_reason": "Doublon"},  # sans date
        {"pickup_point": None},  # Click & Collect sans point de retrait
    ],
)
def test_statuts_incoherents_refuses(fields):
    rejected(update(OrderFactory(), **fields))


def test_statuts_coherents_acceptes():
    now = timezone.now()
    order = OrderFactory()
    Order.objects.filter(pk=order.pk).update(status="ready_for_pickup", ready_at=now)
    Order.objects.filter(pk=order.pk).update(status="collected", collected_at=now)
    other = OrderFactory()
    Order.objects.filter(pk=other.pk).update(
        status="cancelled", cancelled_at=now, cancellation_reason="Doublon"
    )


# --- Attribution par ligne (R09) -----------------------------------------------------------------


def test_attribution_par_ligne_coherente():
    qr = QRCodeFactory()
    variant = VariantFactory(product=qr.product, size="M")
    item = make_order([(variant, 1, qr)]).items.get()
    assert (item.source_qr, item.source_box, item.source_product) == (qr, qr.box, qr.product)
    rows = OrderItem.objects.filter(pk=item.pk)
    rejected(lambda: rows.update(source_box=None))  # incomplète
    rejected(lambda: rows.update(source_product=ProductFactory()))  # produit source ≠ produit de la ligne


def test_instantane_du_produit_conserve():
    variant = VariantFactory(product__name="Polo INP-HB Vert", size="M")
    item = make_order([(variant, 1, None)]).items.get()
    variant.product.name = "Polo INP-HB Vert (nouvelle collection)"
    variant.product.save()
    item.refresh_from_db()
    assert item.product_name == "Polo INP-HB Vert"


# --- Jamais supprimée, historique inaltérable (D.4) -------------------------------------------------


def test_commande_jamais_supprimee():
    order = OrderFactory()
    with pytest.raises(DeletionForbidden):
        order.delete()
    with pytest.raises(DeletionForbidden):
        Order.objects.all().delete()
    assert Order.objects.filter(pk=order.pk).exists()


def test_historique_des_statuts_inalterable():
    entry = OrderStatusHistory.objects.create(order=OrderFactory(), from_status="", to_status="pending")
    for operation in (
        entry.save,
        entry.delete,
        lambda: OrderStatusHistory.objects.update(note="x"),
        lambda: OrderStatusHistory.objects.all().delete(),
    ):
        with pytest.raises(DeletionForbidden):
            operation()


def test_produit_et_variante_commandes_non_supprimables(make_staff):
    variant = VariantFactory(size="M")
    make_order([(variant, 1, None)])
    with pytest.raises(ProtectedError):
        variant.delete()
    with pytest.raises(catalog.ResourceInUse):  # API admin : 409 resource_in_use (étape 8)
        catalog.delete_product(product=variant.product, user=make_staff("ADMIN_GENERAL"))


# --- Données personnelles ---------------------------------------------------------------------


def test_nom_masque_et_coordonnees_normalisees():
    order = OrderFactory.build(
        customer_first_name="awa",
        customer_last_name=" koné",
        customer_phone="07 00 00 00 00",
        customer_email=" Awa.Kone@Exemple.CI ",
        pickup_point=PickupPointFactory(),
    )
    order.full_clean(exclude=["public_reference", "pickup_code"])
    assert order.masked_name == "A. K."
    assert (order.customer_phone, order.customer_email) == ("+2250700000000", "awa.kone@exemple.ci")
    order.customer_phone = "123"
    with pytest.raises(ValidationError):
        order.full_clean(exclude=["public_reference", "pickup_code"])


def test_note_client_limitee_a_500_caracteres():
    order = OrderFactory.build(customer_note="x" * 501, pickup_point=PickupPointFactory())
    with pytest.raises(ValidationError) as info:
        order.full_clean(exclude=["public_reference", "pickup_code"])
    assert "customer_note" in info.value.message_dict
