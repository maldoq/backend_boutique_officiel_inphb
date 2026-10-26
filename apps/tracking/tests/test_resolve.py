"""GET /api/v1/qr/{code}/resolve/ (étape 9)."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.boxes import services as boxes
from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.models import Category, Product
from apps.catalog.tests.factories import CategoryFactory, ProductFactory
from apps.core.throttles import QrResolveIpThrottle, QrResolveThrottle
from apps.tracking.models import TrackingEvent, TrackingEventImmutableError

pytestmark = pytest.mark.django_db

VISITOR = "c0a8f1e2-5b7d-4c11-9e0a-2f6d3b8a9c10"


def resolve(client, code, visitor=VISITOR, **headers):
    if visitor:
        headers["HTTP_X_VISITOR_ID"] = visitor
    return client.get(f"/api/v1/qr/{code}/resolve/", **headers)


def test_reponse_conforme_au_contrat(api_client):
    qr = QRCodeFactory(
        box__code="BOX-CENTRE-01",
        box__label="Box Hall Centre",
        box__site="Centre",
        product__name="Polo INP-HB Vert",
    )
    with freeze_time("2026-10-24T10:12:44Z"):
        response = resolve(api_client, qr.code.lower(), HTTP_X_CLIENT_PLATFORM="android")
    assert response.status_code == 200
    assert response.json() == {
        "qr_code": qr.code,
        "box": {"code": "BOX-CENTRE-01", "label": "Box Hall Centre", "site": "Centre"},
        "product": {"id": qr.product_id, "slug": "polo-inp-hb-vert", "name": "Polo INP-HB Vert"},
        "redirect_path": f"/produits/polo-inp-hb-vert?src={qr.code}",
        "attribution": {
            "source_qr_code": qr.code,
            "source_box_code": "BOX-CENTRE-01",
            "source_product_id": qr.product_id,
            "scanned_at": "2026-10-24T10:12:44Z",
        },
        "visitor_id": VISITOR,
    }
    assert response["X-Visitor-Id"] == VISITOR
    assert response["Cache-Control"] == "no-store"
    event = TrackingEvent.objects.get()
    assert (event.event_type, event.channel, event.qr, event.box, event.product) == (
        "qr_scan",
        "android",
        qr,
        qr.box,
        qr.product,
    )
    assert str(event.visitor_id) == VISITOR


def test_T23_meme_produit_deux_boxes_bonne_attribution(api_client, make_staff):
    agent = make_staff("MARKETING")
    product = ProductFactory(name="Polo INP-HB Vert")
    centre = boxes.create_qr(box=BoxFactory(code="BOX-CENTRE-01"), product=product, user=agent)
    esa = boxes.create_qr(box=BoxFactory(code="BOX-ESA-01"), product=product, user=agent)
    assert resolve(api_client, centre.code).json()["box"]["code"] == "BOX-CENTRE-01"
    assert resolve(api_client, esa.code).json()["box"]["code"] == "BOX-ESA-01"
    assert {(e.qr.code, e.box.code) for e in TrackingEvent.objects.all()} == {
        (centre.code, "BOX-CENTRE-01"),
        (esa.code, "BOX-ESA-01"),
    }


@pytest.mark.parametrize("code", ["INCONNU234", "XYZ", "Q4M8ZK2PT0", "a" * 40])
def test_code_inconnu_ou_impossible_404(api_client, code):
    response = resolve(api_client, code)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "qr_not_found"
    assert not TrackingEvent.objects.exists()


@pytest.mark.parametrize(
    "disable",
    [
        lambda qr, agent: boxes.deactivate_qr(qr=qr, user=agent),
        lambda qr, agent: boxes.regenerate_qr(qr=qr, user=agent),
        lambda qr, agent: boxes.set_box_active(box=qr.box, active=False, user=agent),
        lambda qr, agent: Product.objects.filter(pk=qr.product_id).update(is_active=False),
        lambda qr, agent: Category.objects.filter(pk=qr.product.category_id).update(is_active=False),
    ],
    ids=["qr_desactive", "ancien_code_regenere", "box_inactive", "produit_inactif", "categorie_masquee"],
)
def test_qr_inactif_410(api_client, make_staff, disable):
    qr = QRCodeFactory(product__category=CategoryFactory())
    disable(qr, make_staff("MARKETING"))
    response = resolve(api_client, qr.code)
    assert response.status_code == 410
    assert response.json() == {
        "error": {
            "code": "qr_inactive",
            "message": "Ce QR code n'est plus actif.",
            "details": {"redirect_path": "/"},
        }
    }
    assert not TrackingEvent.objects.exists()


def test_ancien_code_ne_revele_pas_le_nouveau(api_client, make_staff):
    qr = QRCodeFactory()
    new = boxes.regenerate_qr(qr=qr, user=make_staff("MARKETING"))
    assert new.code not in resolve(api_client, qr.code).content.decode()
    assert resolve(api_client, new.code).status_code == 200


def test_produit_bientot_disponible_resolu(api_client):
    qr = QRCodeFactory(product__is_coming_soon=True)
    assert resolve(api_client, qr.code).status_code == 200


def test_box_reactivee_qr_de_nouveau_valide(api_client, make_staff):
    agent = make_staff("MARKETING")
    qr = QRCodeFactory()
    boxes.set_box_active(box=qr.box, active=False, user=agent)
    assert resolve(api_client, qr.code).status_code == 410
    boxes.set_box_active(box=qr.box, active=True, user=agent)
    assert resolve(api_client, qr.code).status_code == 200


# --- Anti-doublon, visiteur, canal ------------------------------------------------------------


def test_rafraichissement_dans_la_fenetre_un_seul_scan(api_client):
    qr = QRCodeFactory()
    start = timezone.now()
    with freeze_time(start):
        first = resolve(api_client, qr.code).json()
    with freeze_time(start + timedelta(seconds=2)):
        second = resolve(api_client, qr.code).json()
    assert TrackingEvent.objects.count() == 1
    assert first["attribution"]["scanned_at"] == second["attribution"]["scanned_at"]
    with freeze_time(start + timedelta(seconds=11)):
        resolve(api_client, qr.code)
    assert TrackingEvent.objects.count() == 2


def test_visiteurs_distincts_scans_distincts(api_client):
    qr = QRCodeFactory()
    resolve(api_client, qr.code, visitor=VISITOR)
    resolve(api_client, qr.code, visitor=str(uuid.uuid4()))
    assert TrackingEvent.objects.count() == 2


@pytest.mark.parametrize("header", [None, "pas-un-uuid", str(uuid.uuid1())])
def test_identifiant_de_visite_absent_ou_invalide_genere(api_client, header):
    qr = QRCodeFactory()
    response = resolve(api_client, qr.code, visitor=header)
    generated = response.json()["visitor_id"]
    assert uuid.UUID(generated).version == 4 and generated != header
    assert response["X-Visitor-Id"] == generated
    assert str(TrackingEvent.objects.get().visitor_id) == generated


def test_canal_inconnu(api_client):
    qr = QRCodeFactory()
    resolve(api_client, qr.code, HTTP_X_CLIENT_PLATFORM="windows-phone")
    assert TrackingEvent.objects.get().channel == "unknown"


# --- Données personnelles (R08) et inaltérabilité ----------------------------------------------


def test_aucune_donnee_personnelle_dans_les_evenements():
    fields = {field.name for field in TrackingEvent._meta.get_fields()}
    assert fields == {
        "id",
        "event_type",
        "occurred_at",
        "visitor_id",
        "channel",
        "qr",
        "box",
        "product",
        "variant",
        "quantity",
        "metadata",
    }


def test_evenement_inalterable_mais_purgeable():
    qr = QRCodeFactory()
    event = TrackingEvent.objects.create(
        event_type="qr_scan", visitor_id=uuid.uuid4(), qr=qr, box=qr.box, product=qr.product
    )
    with pytest.raises(TrackingEventImmutableError):
        event.save()
    with pytest.raises(TrackingEventImmutableError):
        TrackingEvent.objects.update(channel="web")
    TrackingEvent.objects.filter(pk=event.pk).delete()  # purge de rétention (étape 11)
    assert not TrackingEvent.objects.exists()


def test_reaffectation_ne_modifie_pas_l_historique(api_client, make_staff):
    qr = QRCodeFactory(box__code="BOX-CENTRE-01")
    resolve(api_client, qr.code)
    boxes.reassign_qr(qr=qr, box=BoxFactory(code="BOX-ESA-01"), user=make_staff("MARKETING"))
    assert TrackingEvent.objects.get().box.code == "BOX-CENTRE-01"
    assert resolve(api_client, qr.code, visitor=str(uuid.uuid4())).json()["box"]["code"] == "BOX-ESA-01"


# --- Limites de débit (campus : IP partagée) -----------------------------------------------------


def test_limite_par_visiteur_puis_plafond_par_ip(api_client, monkeypatch):
    monkeypatch.setattr(QrResolveThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(QrResolveIpThrottle, "rate", "5/min", raising=False)
    qr = QRCodeFactory()
    same_visitor = [resolve(api_client, qr.code).status_code for _ in range(3)]
    assert same_visitor == [200, 200, 429]
    # Autres visiteurs du même réseau : non bloqués par le compteur du premier.
    others = [resolve(api_client, qr.code, visitor=str(uuid.uuid4())).status_code for _ in range(2)]
    assert others == [200, 200]
    # Plafond par IP atteint (5 requêtes servies au total depuis cette IP).
    assert resolve(api_client, qr.code, visitor=str(uuid.uuid4())).status_code == 429
    assert resolve(api_client, qr.code, visitor=None).json()["error"]["code"] == "throttled"


def test_nouveaux_visiteurs_sans_identifiant_ne_partagent_pas_un_compteur(api_client, monkeypatch):
    monkeypatch.setattr(QrResolveThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(QrResolveIpThrottle, "rate", "100/min", raising=False)
    qr = QRCodeFactory()
    statuses = [resolve(api_client, qr.code, visitor=None).status_code for _ in range(10)]
    assert statuses == [200] * 10  # 10 premiers scans d'étudiants différents sur le Wi-Fi du campus
