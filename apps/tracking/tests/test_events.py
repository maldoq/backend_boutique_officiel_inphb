"""POST /api/v1/tracking/events/ et /batch/ (étape 11) : attribution prouvée, R06, R07, R08."""

import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.boxes import services as boxes
from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.core.throttles import TrackingIpThrottle, TrackingThrottle
from apps.tracking.models import TrackingEvent

pytestmark = pytest.mark.django_db

EVENTS = "/api/v1/tracking/events/"
BATCH = "/api/v1/tracking/events/batch/"


class Visitor:
    """Un visiteur anonyme (identifiant de visite conservé comme le ferait le site ou l'app)."""

    def __init__(self, client, platform="web"):
        self.client, self.id, self.platform = client, str(uuid.uuid4()), platform

    def headers(self):
        return {"HTTP_X_VISITOR_ID": self.id, "HTTP_X_CLIENT_PLATFORM": self.platform}

    def scan(self, qr):
        return self.client.get(f"/api/v1/qr/{qr.code}/resolve/", **self.headers())

    def send(self, **payload):
        return self.client.post(EVENTS, payload, format="json", **self.headers())

    def batch(self, events):
        return self.client.post(BATCH, {"events": events}, format="json", **self.headers())


@pytest.fixture
def visitor(api_client):
    return Visitor(api_client)


@pytest.fixture
def polo():
    product = ProductFactory(variants=False, name="Polo INP-HB Vert")
    VariantFactory(product=product, size="M")
    return product


def last_event():
    return TrackingEvent.objects.order_by("-id").first()


# --- T24 : parcours complet depuis deux boxes, sans mélange ----------------------------------


def test_T24_parcours_depuis_deux_boxes_sans_melange(api_client, polo, make_staff):
    agent = make_staff("MARKETING")
    centre = boxes.create_qr(box=BoxFactory(code="BOX-CENTRE-01"), product=polo, user=agent)
    esa = boxes.create_qr(box=BoxFactory(code="BOX-ESA-01"), product=polo, user=agent)
    variant = polo.variants.get()

    for qr in (centre, esa):
        visitor = Visitor(api_client, platform="android")
        assert visitor.scan(qr).status_code == 200
        view = visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code)
        assert view.status_code == 201 and view.json()["attribution_applied"] is True
        cart = visitor.send(
            event_type="add_to_cart",
            product_slug=polo.slug,
            variant_id=variant.pk,
            quantity=2,
            source_qr_code=qr.code,
        )
        assert cart.json()["attribution_applied"] is True

    journey = {
        (event.event_type, event.box.code)
        for event in TrackingEvent.objects.select_related("box").filter(box__isnull=False)
    }
    assert journey == {
        (t, box)
        for t in ("qr_scan", "product_view", "add_to_cart")
        for box in ("BOX-CENTRE-01", "BOX-ESA-01")
    }
    cart_event = TrackingEvent.objects.get(event_type="add_to_cart", box__code="BOX-ESA-01")
    assert (cart_event.qr, cart_event.variant, cart_event.quantity, cart_event.channel) == (
        esa,
        variant,
        2,
        "android",
    )


def test_reponse_conforme_au_contrat(visitor, polo):
    response = visitor.send(event_type="product_view", product_id=polo.pk)
    assert response.status_code == 201
    assert set(response.json()) == {"id", "recorded", "attribution_applied", "visitor_id"}
    assert response.json()["visitor_id"] == visitor.id == response["X-Visitor-Id"]
    assert response.json()["recorded"] is True and response.json()["attribution_applied"] is False


# --- Attribution prouvée (R06) ----------------------------------------------------------------


def test_code_qr_invente_aucune_attribution(visitor, polo):
    response = visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code="ABCDEFGHJK")
    assert response.status_code == 201 and response.json()["attribution_applied"] is False
    assert last_event().box is None and last_event().qr is None


def test_code_reel_mais_jamais_scanne_par_ce_visiteur(visitor, api_client, polo):
    qr = QRCodeFactory(product=polo)
    Visitor(api_client).scan(qr)  # un AUTRE visiteur a scanné
    response = visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code)
    assert response.json()["attribution_applied"] is False  # code public : pas une preuve


@override_settings(ATTRIBUTION_REQUIRES_SCAN=False)
def test_attribution_sans_preuve_de_scan_si_desactivee(visitor, polo):
    qr = QRCodeFactory(product=polo)
    assert (
        visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code).json()[
            "attribution_applied"
        ]
        is True
    )


def test_produit_different_de_celui_du_qr(visitor, polo):
    qr = QRCodeFactory(product=polo)
    visitor.scan(qr)
    other = ProductFactory()
    response = visitor.send(event_type="product_view", product_id=other.pk, source_qr_code=qr.code)
    assert response.json()["attribution_applied"] is False


def test_box_code_seul_ignore(visitor, polo):
    qr = QRCodeFactory(product=polo, box__code="BOX-CENTRE-01")
    visitor.scan(qr)
    response = visitor.send(event_type="product_view", product_id=polo.pk, box_code="BOX-CENTRE-01")
    assert response.json()["attribution_applied"] is False and last_event().box is None


def test_fenetre_d_attribution(visitor, polo):
    qr = QRCodeFactory(product=polo)
    start = timezone.now()
    with freeze_time(start):
        visitor.scan(qr)
    with freeze_time(start + timedelta(days=6)):
        assert (
            visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code).json()[
                "attribution_applied"
            ]
            is True
        )
    with freeze_time(start + timedelta(days=8)):
        assert (
            visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code).json()[
                "attribution_applied"
            ]
            is False
        )


def test_qr_desactive_apres_le_scan_reste_valable(visitor, polo, make_staff):
    qr = QRCodeFactory(product=polo)
    visitor.scan(qr)
    boxes.deactivate_qr(qr=qr, user=make_staff("MARKETING"))
    assert (
        visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code).json()[
            "attribution_applied"
        ]
        is True
    )


def test_box_du_scan_meme_apres_reaffectation(visitor, polo, make_staff):
    qr = QRCodeFactory(product=polo, box__code="BOX-CENTRE-01")
    visitor.scan(qr)
    boxes.reassign_qr(qr=qr, box=BoxFactory(code="BOX-ESA-01"), user=make_staff("MARKETING"))
    visitor.send(event_type="product_view", product_id=polo.pk, source_qr_code=qr.code)
    assert last_event().box.code == "BOX-CENTRE-01"  # là où le visiteur a vu le produit


# --- Validation ----------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ["qr_scan", "order_created", "inconnu"])
def test_types_reserves_ou_inconnus_400(visitor, polo, event_type):
    response = visitor.send(event_type=event_type, product_id=polo.pk)
    assert response.status_code == 400 and "event_type" in response.json()["error"]["details"]
    assert not TrackingEvent.objects.exists()


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"event_type": "product_view"}, "product_id"),
        ({"event_type": "product_view", "product_id": 999999}, "product_id"),
        ({"event_type": "add_to_cart", "product_id": "{polo}"}, "variant_id"),
        (
            {"event_type": "add_to_cart", "product_id": "{polo}", "variant_id": "{other_variant}"},
            "variant_id",
        ),
        (
            {"event_type": "add_to_cart", "product_id": "{polo}", "variant_id": "{variant}", "quantity": 11},
            "quantity",
        ),
        (
            {"event_type": "add_to_cart", "product_id": "{polo}", "variant_id": "{variant}", "quantity": 0},
            "quantity",
        ),
        (
            {"event_type": "product_view", "product_id": "{polo}", "product_slug": "autre-produit"},
            "product_slug",
        ),
        ({"event_type": "product_view", "product_id": "{hidden}"}, "product_id"),
    ],
)
def test_evenement_invalide_400(visitor, polo, payload, field):
    ids = {
        "{polo}": polo.pk,
        "{variant}": polo.variants.get().pk,
        "{other_variant}": VariantFactory().pk,
        "{hidden}": ProductFactory(is_active=False).pk,
    }
    payload = {
        key: ids.get(value, value) if isinstance(value, str) else value for key, value in payload.items()
    }
    response = visitor.send(**payload)
    assert response.status_code == 400
    assert field in response.json()["error"]["details"]


def test_debut_de_commande_sans_produit(visitor):
    response = visitor.send(event_type="checkout_started")
    assert response.status_code == 201 and last_event().product is None


def test_quantite_par_defaut_et_ignoree_pour_une_consultation(visitor, polo):
    visitor.send(event_type="add_to_cart", product_id=polo.pk, variant_id=polo.variants.get().pk)
    assert last_event().quantity == 1
    visitor.send(event_type="product_view", product_id=polo.pk, quantity=5)
    assert last_event().quantity is None


# --- Horodatage serveur (R07), métadonnées (R08), anti-doublon ---------------------------------------


def test_date_client_ignoree_et_metadonnees_filtrees(api_client, polo):
    visitor = Visitor(api_client, platform="ios")
    with freeze_time("2026-10-24T10:00:00Z"):
        visitor.client.post(
            EVENTS,
            {
                "event_type": "product_view",
                "product_id": polo.pk,
                "occurred_at": "2020-01-01T00:00:00Z",
                "metadata": {
                    "client_timestamp": "2026-10-23T22:00:00Z",
                    "screen": "product_detail",
                    "name": "Awa Koné",
                    "phone": "0700000000",
                    "app_version": "1.2.0",
                },
            },
            format="json",
            **visitor.headers(),
        )
    event = last_event()
    assert event.occurred_at.isoformat() == "2026-10-24T10:00:00+00:00"
    assert event.metadata == {
        "client_timestamp": "2026-10-23T22:00:00Z",
        "screen": "product_detail",
        "app_version": "1.2.0",
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {"screen": "Fiche de Awa Koné"},
        {"client_timestamp": "hier"},
        {"app_version": "<script>"},
        "texte",
        None,
    ],
)
def test_metadonnees_invalides_supprimees(visitor, polo, metadata):
    visitor.send(event_type="product_view", product_id=polo.pk, metadata=metadata)
    assert last_event().metadata == {}


def test_version_de_l_app_reprise_de_l_en_tete(api_client, polo):
    visitor = Visitor(api_client)
    api_client.post(
        EVENTS,
        {"event_type": "product_view", "product_id": polo.pk},
        format="json",
        HTTP_X_APP_VERSION="1.4.2",
        **visitor.headers(),
    )
    assert last_event().metadata == {"app_version": "1.4.2"}


def test_consultation_comptee_une_fois_par_rafraichissement(visitor, polo):
    start = timezone.now()
    with freeze_time(start):
        first = visitor.send(event_type="product_view", product_id=polo.pk)
    with freeze_time(start + timedelta(seconds=3)):
        again = visitor.send(event_type="product_view", product_id=polo.pk)
    assert again.status_code == 200
    assert again.json()["recorded"] is False and again.json()["id"] == first.json()["id"]
    with freeze_time(start + timedelta(seconds=11)):
        assert visitor.send(event_type="product_view", product_id=polo.pk).status_code == 201
    assert TrackingEvent.objects.filter(event_type="product_view").count() == 2


def test_ajouts_au_panier_jamais_dedoublonnes(visitor, polo):
    variant = polo.variants.get()
    for _ in range(3):
        assert (
            visitor.send(event_type="add_to_cart", product_id=polo.pk, variant_id=variant.pk).status_code
            == 201
        )
    assert TrackingEvent.objects.filter(event_type="add_to_cart").count() == 3


# --- Envoi groupé (mobile hors ligne) -------------------------------------------------------------


def test_lot_valide_independamment(visitor, polo):
    qr = QRCodeFactory(product=polo)
    visitor.scan(qr)
    variant = polo.variants.get()
    response = visitor.batch(
        [
            {"event_type": "product_view", "product_id": polo.pk, "source_qr_code": qr.code},
            {"event_type": "qr_scan", "product_id": polo.pk},
            {
                "event_type": "add_to_cart",
                "product_id": polo.pk,
                "variant_id": variant.pk,
                "source_qr_code": qr.code,
                "metadata": {"client_timestamp": "2026-10-24T08:00:00Z"},
            },
            {"event_type": "add_to_cart", "product_id": polo.pk},
        ]
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 2 and body["visitor_id"] == visitor.id
    assert [r["index"] for r in body["rejected"]] == [1, 3]
    assert body["rejected"][0]["error"]["code"] == "validation_error"
    assert TrackingEvent.objects.filter(event_type="add_to_cart", qr=qr).exists()


@pytest.mark.parametrize("events", [[], [{"event_type": "checkout_started"}] * 21, "pas une liste"])
def test_lot_vide_trop_grand_ou_invalide_400(visitor, events):
    assert visitor.batch(events).status_code == 400
    assert not TrackingEvent.objects.exists()


# --- Limites de débit (campus) ------------------------------------------------------------------


def test_limite_par_visiteur_puis_par_ip(api_client, polo, monkeypatch):
    monkeypatch.setattr(TrackingThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(TrackingIpThrottle, "rate", "5/min", raising=False)
    first = Visitor(api_client)
    statuses = [first.send(event_type="checkout_started").status_code for _ in range(3)]
    assert statuses[2] == 429 and 429 not in statuses[:2]
    # Les autres visiteurs du même réseau ne sont pas bloqués par le compteur du premier…
    assert Visitor(api_client).send(event_type="checkout_started").status_code in (200, 201)
    assert Visitor(api_client).send(event_type="checkout_started").status_code in (200, 201)
    # … jusqu'au plafond de l'IP (les requêtes refusées d'un abuseur comptent dans ce plafond).
    assert Visitor(api_client).send(event_type="checkout_started").status_code == 429
