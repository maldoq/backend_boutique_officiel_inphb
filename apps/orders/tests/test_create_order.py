"""POST /api/v1/cart/validate/, POST /api/v1/orders/, suivi (étape 13) : T05, T06, T07, T08, T24."""

import uuid

import pytest

from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.core.models import SiteSettings
from apps.core.throttles import OrderCreateIpThrottle, OrderCreateThrottle, OrderLookupReferenceThrottle
from apps.inventory.models import StockMovement
from apps.orders import services
from apps.orders.models import Order, OrderStatusHistory, PickupPoint
from apps.tracking.models import TrackingEvent

pytestmark = pytest.mark.django_db

ORDERS = "/api/v1/orders/"
CART = "/api/v1/cart/validate/"


class Client:
    """Un visiteur du site ou de l'application (identifiant de visite conservé)."""

    def __init__(self, api_client, platform="web"):
        self.api, self.visitor, self.platform = api_client, str(uuid.uuid4()), platform

    def headers(self, **extra):
        return {"HTTP_X_VISITOR_ID": self.visitor, "HTTP_X_CLIENT_PLATFORM": self.platform, **extra}

    def scan(self, qr):
        return self.api.get(f"/api/v1/qr/{qr.code}/resolve/", **self.headers())

    def order(self, payload, key=None):
        extra = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return self.api.post(ORDERS, payload, format="json", **self.headers(**extra))

    def cart(self, items):
        return self.api.post(CART, {"items": items}, format="json", **self.headers())


@pytest.fixture
def client(api_client):
    return Client(api_client)


@pytest.fixture
def polo():
    product = ProductFactory(
        variants=False, name="Polo INP-HB Vert", reference="INP-TEX-001", price_xof=12000
    )
    VariantFactory(product=product, size="M", color="Vert", stock_quantity=10)
    VariantFactory(product=product, size="XL", color="Vert", stock_quantity=0)
    return product


def variant(product, size):
    return product.variants.get(size=size)


def payload(items, **overrides):
    data = {
        "customer": {
            "first_name": "Awa",
            "last_name": "Koné",
            "phone": "07 00 00 00 00",
            "email": "Awa@Exemple.ci",
        },
        "fulfillment_method": "click_and_collect",
        "pickup_point_id": PickupPoint.objects.get(code="BOUTIQUE-CENTRE").pk,
        "items": items,
        "customer_note": "",
        "accept_terms": True,
    }
    data.update(overrides)
    return data


def stock(v) -> int:
    return ProductVariant.objects.get(pk=v.pk).stock_quantity


# --- T06 : commande invitée valide -------------------------------------------------------------


def test_T06_commande_invitee_valide(client, polo):
    m = variant(polo, "M")
    response = client.order(payload([{"variant_id": m.pk, "quantity": 2}]))
    assert response.status_code == 201
    data = response.json()
    assert data["public_reference"].startswith("CMD-") and len(data["public_reference"]) == 12
    assert len(data["pickup_code"]) == 6
    assert data["pickup_qr_payload"] == f"INPHB-PICKUP:{data['public_reference']}:{data['pickup_code']}"
    assert (data["status"], data["status_label"]) == ("pending", "En attente de validation")
    assert (data["payment_status"], data["payment_status_label"]) == ("unpaid", "Non payée")
    assert "pas encore activé" in data["payment_message"]
    assert data["pickup_point"]["name"] == "Boutique INP-HB Centre"
    assert data["customer"] == {
        "first_name": "Awa",
        "last_name": "Koné",
        "phone": "+2250700000000",
        "email": "awa@exemple.ci",
    }
    assert data["items"] == [
        {
            "product_name": "Polo INP-HB Vert",
            "variant_label": "M / Vert",
            "sku": m.sku,
            "unit_price_xof": 12000,
            "quantity": 2,
            "line_total_xof": 24000,
            "source": None,
        }
    ]
    assert (data["subtotal_xof"], data["total_xof"], data["currency"]) == (24000, 24000, "XOF")
    assert data["warnings"] == []
    assert response["Cache-Control"] == "no-store"

    order = Order.objects.get()
    assert (order.channel, str(order.visitor_id)) == ("web", client.visitor)
    assert order.accepted_terms_at is not None
    assert stock(m) == 8
    movement = StockMovement.objects.get()
    assert (movement.reason, movement.delta, movement.order, movement.created_by) == (
        "order_reserved",
        -2,
        order,
        None,
    )
    assert list(OrderStatusHistory.objects.values_list("from_status", "to_status")) == [("", "pending")]
    assert TrackingEvent.objects.filter(event_type="order_created", order=order).count() == 1


# --- T05 : prix falsifié ---------------------------------------------------------------------------


def test_T05_prix_et_total_falsifies_ignores(client, polo):
    m = variant(polo, "M")
    forged = payload(
        [{"variant_id": m.pk, "quantity": 1, "unit_price_xof": 1, "line_total_xof": 1}],
        total_xof=1,
        subtotal_xof=1,
        payment_status="paid",
        status="collected",
    )
    data = client.order(forged).json()
    assert (data["items"][0]["unit_price_xof"], data["total_xof"]) == (12000, 12000)
    assert (data["status"], data["payment_status"]) == ("pending", "unpaid")


# --- T07 : stock insuffisant -----------------------------------------------------------------------


def test_T07_stock_insuffisant_rien_n_est_cree(client):
    product = ProductFactory(variants=False, name="Carnet")
    low = VariantFactory(product=product, size="A5", stock_quantity=2)
    other = VariantFactory(product=product, size="A4", stock_quantity=1)
    response = client.order(
        payload([{"variant_id": low.pk, "quantity": 3}, {"variant_id": other.pk, "quantity": 2}])
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "insufficient_stock"
    assert error["details"]["items"] == [  # toutes les variantes en défaut, d'un coup
        {"variant_id": low.pk, "requested": 3, "available": 2},
        {"variant_id": other.pk, "requested": 2, "available": 1},
    ]
    assert (stock(low), stock(other)) == (2, 1)
    assert not Order.objects.exists() and not StockMovement.objects.exists()
    assert not TrackingEvent.objects.filter(event_type="order_created").exists()


# --- T08 / T24 : attribution par ligne ------------------------------------------------------------------


def test_T24_parcours_complet_scan_panier_commande_par_box(api_client, polo):
    m = variant(polo, "M")
    centre = QRCodeFactory(product=polo, box=BoxFactory(code="BOX-CENTRE-01"))
    esa = QRCodeFactory(product=polo, box=BoxFactory(code="BOX-ESA-01"))
    for qr, quantity in ((centre, 2), (esa, 1)):
        client = Client(api_client, platform="android")
        assert client.scan(qr).status_code == 200
        client.api.post(
            "/api/v1/tracking/events/",
            {
                "event_type": "add_to_cart",
                "product_id": polo.pk,
                "variant_id": m.pk,
                "source_qr_code": qr.code,
            },
            format="json",
            **client.headers(),
        )
        data = client.order(
            payload([{"variant_id": m.pk, "quantity": quantity, "source_qr_code": qr.code}])
        ).json()
        assert data["items"][0]["source"] == {"qr_code": qr.code, "box_code": qr.box.code}
        assert data["warnings"] == []

    for qr in (centre, esa):
        item = Order.objects.get(items__source_qr=qr).items.get()
        assert (item.source_qr, item.source_box, item.source_product) == (qr, qr.box, polo)
        assert Order.objects.get(items__source_qr=qr).source_box == qr.box
        assert TrackingEvent.objects.filter(event_type="order_created", qr=qr, box=qr.box).count() == 1
    assert stock(m) == 7


def test_qr_invente_ou_non_scanne_commande_sans_attribution(client, polo):
    m = variant(polo, "M")
    real = QRCodeFactory(product=polo)  # jamais scanné par ce visiteur
    response = client.order(
        payload(
            [
                {"variant_id": m.pk, "quantity": 1, "source_qr_code": "INVENTE23"},
                {"variant_id": m.pk, "quantity": 1, "source_qr_code": real.code},
            ]
        )
    )
    assert response.status_code == 201
    warnings = response.json()["warnings"]
    assert [w["code"] for w in warnings] == ["attribution_ignored", "attribution_ignored"]
    assert all(item["source"] is None for item in response.json()["items"])
    assert not Order.objects.get().items.filter(source_qr__isnull=False).exists()


# --- Fusion des lignes et limites ----------------------------------------------------------------------


def test_lignes_identiques_fusionnees_meme_variante_qr_differents_conservees(client, polo):
    m = variant(polo, "M")
    qr = QRCodeFactory(product=polo)
    client.scan(qr)
    response = client.order(
        payload(
            [
                {"variant_id": m.pk, "quantity": 1, "source_qr_code": qr.code},
                {"variant_id": m.pk, "quantity": 2, "source_qr_code": qr.code.lower()},
                {"variant_id": m.pk, "quantity": 1},
            ]
        )
    )
    items = response.json()["items"]
    assert sorted(i["quantity"] for i in items) == [1, 3]
    assert stock(m) == 6


def test_limite_de_quantite_sur_le_total_par_variante(client):
    big = VariantFactory(stock_quantity=100)
    lines = [{"variant_id": big.pk, "quantity": 6, "source_qr_code": "FAUX" + str(i) * 4} for i in range(2)]
    response = client.order(payload(lines))  # 6 + 6 = 12 > 10, malgré deux « QR » différents
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "quantity_limit_exceeded"
    assert stock(big) == 100


@pytest.mark.parametrize(
    ("make", "status_code", "code"),
    [
        (lambda: VariantFactory(is_active=False), 409, "product_unavailable"),
        (lambda: VariantFactory(product__is_active=False), 409, "product_unavailable"),
        (lambda: VariantFactory(product__is_coming_soon=True), 409, "product_unavailable"),
        (lambda: VariantFactory(product__category__is_active=False), 409, "product_unavailable"),
    ],
)
def test_article_non_commandable(client, make, status_code, code):
    response = client.order(payload([{"variant_id": make().pk, "quantity": 1}]))
    assert response.status_code == status_code and response.json()["error"]["code"] == code
    assert not Order.objects.exists()


def test_article_inconnu_404(client):
    response = client.order(payload([{"variant_id": 999999, "quantity": 1}]))
    assert response.status_code == 404 and response.json()["error"]["details"]["items"] == [
        {"variant_id": 999999}
    ]


def test_point_de_retrait_inconnu_ou_inactif(client, polo):
    closed = PickupPoint.objects.create(code="POINT-FERME", name="Fermé", is_active=False)
    for pickup_point_id in (closed.pk, 999999):
        response = client.order(
            payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}], pickup_point_id=pickup_point_id)
        )
        assert response.status_code == 400 and response.json()["error"]["code"] == "pickup_point_unavailable"


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"customer": {"first_name": "A", "last_name": "Koné", "phone": "0700000000"}}, "customer"),
        ({"customer": {"first_name": "Awa", "last_name": "Koné", "phone": "12345"}}, "customer"),
        (
            {"customer": {"first_name": "Awa", "last_name": "Koné", "phone": "0700000000", "email": "x@"}},
            "customer",
        ),
        ({"items": []}, "items"),
        ({"customer_note": "x" * 501}, "customer_note"),
        ({"fulfillment_method": "delivery"}, "fulfillment_method"),
    ],
)
def test_donnees_invalides_400(client, polo, override, field):
    body = payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}])
    body.update(override)
    response = client.order(body)
    assert response.status_code == 400 and field in response.json()["error"]["details"]


def test_trop_de_lignes(client):
    lines = [{"variant_id": VariantFactory().pk, "quantity": 1} for _ in range(31)]
    assert client.order(payload(lines)).status_code == 400


def test_mode_maintenance_503(client, polo):
    site = SiteSettings.load()
    site.maintenance_mode = True
    site.save()
    response = client.order(payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}]))
    assert response.status_code == 503 and response.json()["error"]["code"] == "maintenance_mode"


# --- Idempotence ---------------------------------------------------------------------------------


def test_idempotence_meme_commande_stock_decremente_une_fois(client, polo):
    m = variant(polo, "M")
    body = payload([{"variant_id": m.pk, "quantity": 2}])
    key = str(uuid.uuid4())
    first = client.order(body, key=key)
    again = client.order(body, key=key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["public_reference"] == first.json()["public_reference"]
    assert again.json()["pickup_code"] == first.json()["pickup_code"]
    assert Order.objects.count() == 1 and stock(m) == 8


def test_meme_cle_autre_contenu_409(client, polo):
    key = str(uuid.uuid4())
    m = variant(polo, "M")
    client.order(payload([{"variant_id": m.pk, "quantity": 1}]), key=key)
    response = client.order(payload([{"variant_id": m.pk, "quantity": 3}]), key=key)
    assert response.status_code == 409 and response.json()["error"]["code"] == "idempotency_conflict"
    assert "pickup_code" not in response.content.decode()
    assert stock(m) == 9


def test_cle_d_idempotence_mal_formee(client, polo):
    response = client.order(payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}]), key="a b")
    assert response.status_code == 400 and "Idempotency-Key" in response.json()["error"]["details"]


def test_envois_simultanes_meme_cle(client, polo, monkeypatch):
    """La transaction perdante (clé déjà prise en base) est annulée, la commande gagnante est renvoyée."""
    m = variant(polo, "M")
    body = payload([{"variant_id": m.pk, "quantity": 2}])
    key = str(uuid.uuid4())
    winner = client.order(body, key=key).json()
    original = services.find_by_idempotency_key
    calls = {"n": 0}

    def stale_first_lookup(value):
        calls["n"] += 1
        return (
            None if calls["n"] == 1 else original(value)
        )  # la course : la commande n'était pas encore visible

    monkeypatch.setattr(services, "find_by_idempotency_key", stale_first_lookup)
    replay = client.order(body, key=key)
    assert replay.status_code == 200 and replay.json()["public_reference"] == winner["public_reference"]
    assert Order.objects.count() == 1 and stock(m) == 8  # la réservation perdante a été annulée


# --- Notification après validation -----------------------------------------------------------------


def test_signal_order_created_apres_validation(client, polo, django_capture_on_commit_callbacks):
    from apps.orders.signals import order_created

    received = []
    order_created.connect(
        lambda sender, order, **kw: received.append(order.public_reference),
        weak=False,
        dispatch_uid="test_order_created",
    )
    try:
        with django_capture_on_commit_callbacks(execute=True):
            reference = client.order(payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}])).json()[
                "public_reference"
            ]
        assert received == [reference]
    finally:
        order_created.disconnect(dispatch_uid="test_order_created")


# --- Validation du panier ------------------------------------------------------------------------


def test_panier_conforme_au_contrat_sans_ecriture(client, polo):
    m, xl = variant(polo, "M"), variant(polo, "XL")
    qr = QRCodeFactory(product=polo)
    client.scan(qr)
    events_before = TrackingEvent.objects.count()
    response = client.cart(
        [
            {"variant_id": m.pk, "quantity": 2, "source_qr_code": qr.code, "expected_unit_price_xof": 12000},
            {"variant_id": xl.pk, "quantity": 1},
        ]
    )
    assert response.status_code == 200
    data = response.json()
    first, second = data["items"]
    assert (first["unit_price_xof"], first["line_total_xof"], first["issues"]) == (12000, 24000, [])
    assert (first["max_orderable_quantity"], first["attribution_applied"]) == (10, True)
    assert second["availability"] == "out_of_stock" and second["issues"][0]["code"] == "out_of_stock"
    assert (data["subtotal_xof"], data["total_xof"], data["currency"], data["is_valid"]) == (
        36000,
        36000,
        "XOF",
        False,
    )
    assert not Order.objects.exists() and not StockMovement.objects.exists()
    assert TrackingEvent.objects.count() == events_before


def test_panier_prix_change_non_bloquant_et_limites(client, polo):
    m = variant(polo, "M")
    data = client.cart([{"variant_id": m.pk, "quantity": 1, "expected_unit_price_xof": 10000}]).json()
    assert [i["code"] for i in data["items"][0]["issues"]] == ["price_changed"] and data["is_valid"] is True
    over = client.cart([{"variant_id": m.pk, "quantity": 11}]).json()
    assert {i["code"] for i in over["items"][0]["issues"]} >= {
        "insufficient_stock",
        "quantity_limit_exceeded",
    }
    assert over["is_valid"] is False
    unknown = client.cart([{"variant_id": 999999, "quantity": 1}]).json()
    assert unknown["items"][0]["issues"][0]["code"] == "product_unavailable" and unknown["is_valid"] is False


# --- Suivi --------------------------------------------------------------------------------------


@pytest.fixture
def placed(client, polo):
    return client.order(payload([{"variant_id": variant(polo, "M").pk, "quantity": 1}])).json()


def test_suivi_public_sans_donnee_personnelle(api_client, placed):
    response = api_client.get(f"{ORDERS}{placed['public_reference'].lower()}/")
    assert response.status_code == 200
    data = response.json()
    assert data["customer_name"] == "A. K."
    body = response.content.decode()
    for secret in (placed["pickup_code"], "0700000000", "awa@exemple.ci", "Koné"):
        assert secret not in body
    assert api_client.get(f"{ORDERS}CMD-INCONNU2/").status_code == 404


@pytest.mark.parametrize("phone", ["0700000000", "+225 07 00 00 00 00", "002250700000000"])
def test_retrouver_sa_commande_avec_le_telephone(api_client, placed, phone):
    response = api_client.post(
        f"{ORDERS}lookup/",
        {"public_reference": placed["public_reference"].lower(), "phone": phone},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["pickup_code"] == placed["pickup_code"]


def test_retrouver_reponse_generique(api_client, placed):
    wrong_phone = api_client.post(
        f"{ORDERS}lookup/",
        {"public_reference": placed["public_reference"], "phone": "0500000000"},
        format="json",
    )
    unknown_ref = api_client.post(
        f"{ORDERS}lookup/", {"public_reference": "CMD-INCONNU2", "phone": "0700000000"}, format="json"
    )
    assert wrong_phone.status_code == unknown_ref.status_code == 404
    assert wrong_phone.json() == unknown_ref.json()  # rien ne révèle si la référence existe


def test_force_brute_limitee_par_reference(api_client, placed, monkeypatch):
    monkeypatch.setattr(OrderLookupReferenceThrottle, "rate", "3/hour", raising=False)
    attempts = [
        api_client.post(
            f"{ORDERS}lookup/",
            {"public_reference": placed["public_reference"], "phone": f"05000000{i:02d}"},
            format="json",
            REMOTE_ADDR=f"10.0.0.{i}",
        ).status_code  # IP différente à chaque essai
        for i in range(4)
    ]
    assert attempts == [404, 404, 404, 429]


# --- Limites de débit (campus) -------------------------------------------------------------------


def test_limite_commandes_par_visiteur_puis_par_ip(api_client, monkeypatch):
    monkeypatch.setattr(OrderCreateThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(OrderCreateIpThrottle, "rate", "4/min", raising=False)
    v = VariantFactory(stock_quantity=100)
    first = Client(api_client)
    statuses = [first.order(payload([{"variant_id": v.pk, "quantity": 1}])).status_code for _ in range(3)]
    assert statuses == [201, 201, 429]
    assert Client(api_client).order(payload([{"variant_id": v.pk, "quantity": 1}])).status_code == 201
    assert Client(api_client).order(payload([{"variant_id": v.pk, "quantity": 1}])).status_code == 429
