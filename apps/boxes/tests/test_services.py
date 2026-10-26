import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boxes import services
from apps.boxes.models import Box, QRCode, normalize_qr_code
from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.tests.factories import CategoryFactory, ProductFactory
from apps.core.codes import ALPHABET
from apps.core.exceptions import ConflictError

pytestmark = pytest.mark.django_db


@pytest.fixture
def agent(make_staff):
    return make_staff("MARKETING")


# --- Boxes ------------------------------------------------------------------------------


def test_code_de_box_normalise_avant_validation(agent):
    box = services.create_box(
        data={"code": " box centre 01 ", "label": "Box Hall Centre", "site": "Centre"}, user=agent
    )
    assert box.code == "BOX-CENTRE-01"
    assert AuditLog.objects.get(action="box.create").object_id == str(box.pk)
    with pytest.raises(ValidationError) as info:
        services.create_box(data={"code": "CENTRE-01", "label": "x", "site": "Centre"}, user=agent)
    assert "code" in info.value.detail
    with pytest.raises(ValidationError):  # doublon après normalisation
        services.create_box(data={"code": "box-centre-01", "label": "x", "site": "Centre"}, user=agent)


def test_desactivation_de_box_auditee_sans_toucher_aux_qr(agent):
    qr = QRCodeFactory()
    services.set_box_active(box=qr.box, active=False, user=agent)
    qr.refresh_from_db()
    assert qr.is_active  # le QR n'est pas modifié : il redevient utilisable à la réactivation
    assert AuditLog.objects.get(action="box.deactivate").changes == {"is_active": [True, False]}


def test_box_avec_qr_non_supprimable():
    qr = QRCodeFactory()
    with pytest.raises(ProtectedError):
        qr.box.delete()
    with pytest.raises(ProtectedError):
        qr.product.delete()


# --- Création -----------------------------------------------------------------------------


def test_T23_un_qr_distinct_par_box_pour_le_meme_produit(agent):
    product = ProductFactory(name="Polo INP-HB Vert")
    centre, esa = BoxFactory(code="BOX-CENTRE-01"), BoxFactory(code="BOX-ESA-01")
    first = services.create_qr(box=centre, product=product, user=agent)
    second = services.create_qr(box=esa, product=product, user=agent)
    assert first.code != second.code and first.public_url != second.public_url
    assert len(first.code) == 10 and set(first.code) <= set(ALPHABET)
    assert first.public_url == f"http://boutique.test/q/{first.code}"
    assert (first.created_by, first.is_active, first.activated_at is not None) == (agent, True, True)
    assert AuditLog.objects.filter(action="qr.create").count() == 2


def test_un_seul_qr_actif_par_couple(agent):
    qr = QRCodeFactory()
    with pytest.raises(ConflictError) as info:
        services.create_qr(box=qr.box, product=qr.product, user=agent)
    assert info.value.code == "qr_conflict"
    assert info.value.details == {"qr_code": qr.code}
    with pytest.raises(IntegrityError), transaction.atomic():  # garantie finale en base
        QRCodeFactory(box=qr.box, product=qr.product)


@pytest.mark.parametrize(
    "make_target",
    [
        lambda: (BoxFactory(is_active=False), ProductFactory()),
        lambda: (BoxFactory(), ProductFactory(is_active=False)),
        lambda: (BoxFactory(), ProductFactory(category=CategoryFactory(is_active=False))),
    ],
    ids=["box_inactive", "produit_inactif", "categorie_masquee"],
)
def test_pas_de_qr_mort(agent, make_target):
    box, product = make_target()
    with pytest.raises(ValidationError):
        services.create_qr(box=box, product=product, user=agent)
    assert not QRCode.objects.exists()


# --- Désactivation / réactivation / régénération / réaffectation ------------------------------


def test_desactivation_et_reactivation(agent):
    qr = QRCodeFactory()
    services.deactivate_qr(qr=qr, user=agent)
    qr.refresh_from_db()
    assert not qr.is_active and qr.deactivated_at
    services.deactivate_qr(qr=qr, user=agent)  # idempotent, pas de seconde trace
    assert AuditLog.objects.filter(action="qr.deactivate").count() == 1
    QRCodeFactory(box=qr.box, product=qr.product)  # un autre QR actif a pris la place
    with pytest.raises(ConflictError) as info:
        services.activate_qr(qr=qr, user=agent)
    assert info.value.code == "qr_conflict"


def test_regeneration(agent):
    old = QRCodeFactory()
    new = services.regenerate_qr(qr=old, user=agent)
    old.refresh_from_db()
    assert new.code != old.code and new.is_active
    assert (new.box_id, new.product_id) == (old.box_id, old.product_id)
    assert not old.is_active and old.replaced_by == new and old.deactivated_at
    assert AuditLog.objects.get(action="qr.regenerate").changes["replaced_by"] == [None, new.code]
    assert AuditLog.objects.get(action="qr.create").changes["replaces"] == [None, old.code]
    for operation in (services.regenerate_qr, services.activate_qr):
        with pytest.raises(ConflictError) as info:
            operation(qr=old, user=agent)
        assert info.value.code == "qr_replaced"


def test_reaffectation_meme_code_nouvelle_destination(agent):
    qr = QRCodeFactory()
    code = qr.code
    other_box, other_product = BoxFactory(), ProductFactory()
    services.reassign_qr(qr=qr, box=other_box, product=other_product, user=agent)
    qr.refresh_from_db()
    assert (qr.code, qr.box, qr.product) == (code, other_box, other_product)
    entry = AuditLog.objects.get(action="qr.reassign")
    assert set(entry.changes) == {"box", "product"}


def test_reaffectation_refusee(agent):
    qr = QRCodeFactory()
    occupied = QRCodeFactory(product=qr.product)
    with pytest.raises(ConflictError):
        services.reassign_qr(qr=qr, box=occupied.box, user=agent)
    with pytest.raises(ValidationError):
        services.reassign_qr(qr=qr, user=agent)  # aucune nouvelle destination
    with pytest.raises(ValidationError):
        services.reassign_qr(qr=qr, product=ProductFactory(is_active=False), user=agent)


# --- Codes et configuration -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" q4m8 zk2pta ", "Q4M8ZK2PTA"),
        ("q4m8zk2pta", "Q4M8ZK2PTA"),
        ("Q4M8ZK2PT0", None),
        ("ABC", None),
        ("A" * 17, None),
        ("../../etc", None),
        ("", None),
    ],
)
def test_normalisation_du_code_qr(raw, expected):
    assert normalize_qr_code(raw) == expected


def test_box_modele_normalise_le_code():
    box = Box(code="box esa 01", label="Box ESA", site="ESA")
    box.full_clean()
    assert box.code == "BOX-ESA-01"
    with pytest.raises(DjangoValidationError):
        Box(code="ESA", label="x", site="ESA").full_clean()


@override_settings(QR_CODE_LENGTH=6)
def test_controle_de_la_longueur_des_codes(capsys):
    from django.core.management.base import SystemCheckError

    with pytest.raises(SystemCheckError):
        call_command("check")


@override_settings(DEBUG=False, PUBLIC_WEB_BASE_URL="http://localhost:4200")
def test_controle_deploiement_url_publique_des_qr():
    from apps.core.checks import public_web_base_url_check

    assert [w.id for w in public_web_base_url_check(None)] == ["core.W001"]
    with override_settings(PUBLIC_WEB_BASE_URL="https://boutique.inphb.ci"):
        assert public_web_base_url_check(None) == []
