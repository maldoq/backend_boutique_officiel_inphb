"""Points de retrait (public, /app/config/), liens commande ↔ stock / traçabilité, Django Admin."""

import pytest
from django.db import transaction

from apps.boxes.tests.factories import QRCodeFactory
from apps.catalog.tests.factories import VariantFactory
from apps.inventory.choices import StockReason
from apps.inventory.services import apply_movement
from apps.orders.models import PickupPoint
from apps.orders.tests.factories import OrderFactory, PickupPointFactory, make_order
from apps.tracking.models import TrackingEvent
from apps.tracking.services import record_order_created

pytestmark = pytest.mark.django_db


# --- GET /api/v1/pickup-points/ ------------------------------------------------------------------


def test_points_de_retrait_actifs_tries(api_client):
    PickupPointFactory(code="POINT-ESA", name="Point ESA", position=2, opening_hours="Lun–Ven")
    PickupPointFactory(code="POINT-FERME", name="Fermé", is_active=False)
    response = api_client.get("/api/v1/pickup-points/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "public, max-age=60"
    data = response.json()
    assert [point["code"] for point in data] == ["BOUTIQUE-CENTRE", "POINT-ESA"]
    assert set(data[0]) == {"id", "code", "name", "address", "instructions", "opening_hours", "phone"}


def test_points_de_retrait_dans_la_configuration_mobile(api_client):
    centre = PickupPoint.objects.get(code="BOUTIQUE-CENTRE")
    data = api_client.get("/api/v1/app/config/").json()
    assert data["pickup_points"] == [
        {
            "id": centre.pk,
            "code": "BOUTIQUE-CENTRE",
            "name": "Boutique INP-HB Centre",
            "address": "",
            "opening_hours": "",
        }
    ]


# --- Liens vers la commande ------------------------------------------------------------------


def test_mouvement_de_stock_lie_a_la_commande():
    variant = VariantFactory(stock_quantity=5)
    order = make_order([(variant, 2, None)])
    with transaction.atomic():
        movement = apply_movement(variant=variant, delta=-2, reason=StockReason.ORDER_RESERVED, order=order)
    assert movement.order == order
    assert list(order.stock_movements.all()) == [movement]


def test_evenements_order_created_par_qr_source():
    centre = QRCodeFactory(box__code="BOX-CENTRE-01")
    esa = QRCodeFactory(box__code="BOX-ESA-01", product=centre.product)
    variant = VariantFactory(product=centre.product, size="M")
    other = VariantFactory(product=centre.product, size="L")
    order = make_order(
        [(variant, 1, centre), (other, 1, centre), (variant, 2, esa), (other, 1, None)], channel="android"
    )

    events = record_order_created(order)

    assert len(events) == 3  # un par QR distinct + un sans source
    stored = TrackingEvent.objects.filter(event_type="order_created", order=order)
    assert {(e.qr_id, e.box_id) for e in stored} == {
        (centre.pk, centre.box_id),
        (esa.pk, esa.box_id),
        (None, None),
    }
    assert {e.channel for e in stored} == {"android"} and {e.visitor_id for e in stored} == {order.visitor_id}
    assert list(order.tracking_events.all()) != []


def test_order_created_sans_ligne_attribuee():
    order = make_order([(VariantFactory(), 1, None)])
    events = record_order_created(order)
    assert len(events) == 1 and events[0].qr_id is None and events[0].order == order


# --- Django Admin --------------------------------------------------------------------------------


@pytest.fixture
def staff_client(client, make_staff):
    client.force_login(make_staff(is_superuser=True))
    return client


def test_commandes_en_lecture_seule_dans_django_admin(staff_client):
    order = make_order([(VariantFactory(), 1, None)])
    url = f"/django-admin/orders/order/{order.pk}/change/"
    page = staff_client.get(url)
    assert page.status_code == 200 and order.public_reference in page.content.decode()
    assert staff_client.post(url, {"status": "collected"}).status_code == 403
    assert staff_client.get("/django-admin/orders/order/add/").status_code == 403
    assert staff_client.get(f"/django-admin/orders/order/{order.pk}/delete/").status_code == 403
    assert staff_client.get("/django-admin/orders/order/").status_code == 200


def test_point_de_retrait_dans_django_admin_audite(staff_client):
    from apps.audit.models import AuditLog

    response = staff_client.post(
        "/django-admin/orders/pickuppoint/add/",
        {"code": "point esa", "name": "Point ESA", "is_active": "on", "position": 1},
    )
    assert response.status_code == 302
    point = PickupPoint.objects.get(code="POINT-ESA")
    assert AuditLog.objects.get(action="pickup_point.create").object_id == str(point.pk)
    assert staff_client.get(f"/django-admin/orders/pickuppoint/{point.pk}/delete/").status_code == 403


def test_commande_rattachee_au_point_de_retrait_initial():
    order = OrderFactory(pickup_point=PickupPoint.objects.get(code="BOUTIQUE-CENTRE"))
    assert order.pickup_point.name == "Boutique INP-HB Centre"
