import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import QRCode
from apps.boxes.tests.factories import BoxFactory, QRCodeFactory
from apps.catalog.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, make_staff):
    client.force_login(make_staff(email="root@exemple.ci", is_superuser=True))
    return client


def test_pages(staff_client):
    qr = QRCodeFactory()
    for url in (
        "/django-admin/boxes/box/",
        "/django-admin/boxes/box/add/",
        f"/django-admin/boxes/box/{qr.box.pk}/change/",
        "/django-admin/boxes/qrcode/",
        "/django-admin/boxes/qrcode/add/",
        f"/django-admin/boxes/qrcode/{qr.pk}/change/",
        "/django-admin/tracking/trackingevent/",
    ):
        assert staff_client.get(url).status_code == 200, url
    assert qr.public_url in staff_client.get(f"/django-admin/boxes/qrcode/{qr.pk}/change/").content.decode()


def test_creation_de_box_et_de_qr_auditee(staff_client):
    response = staff_client.post(
        "/django-admin/boxes/box/add/",
        {"code": "box centre 01", "label": "Box Hall Centre", "site": "Centre", "is_active": "on"},
    )
    assert response.status_code == 302
    box = BoxFactory._meta.model.objects.get(code="BOX-CENTRE-01")
    product = ProductFactory()
    response = staff_client.post(
        "/django-admin/boxes/qrcode/add/", {"box": box.pk, "product": product.pk, "note": "Étagère haute"}
    )
    assert response.status_code == 302
    qr = QRCode.objects.get()
    assert len(qr.code) == 10 and qr.is_active
    assert {e.action for e in AuditLog.objects.all()} >= {"box.create", "qr.create"}


def test_doublon_refuse_avec_message(staff_client):
    qr = QRCodeFactory()
    response = staff_client.post(
        "/django-admin/boxes/qrcode/add/", {"box": qr.box.pk, "product": qr.product.pk}
    )
    assert response.status_code == 200
    assert "existe déjà" in response.content.decode()
    assert QRCode.objects.count() == 1


def test_reaffectation_et_desactivation_depuis_le_formulaire(staff_client):
    qr = QRCodeFactory()
    other = BoxFactory()
    response = staff_client.post(
        f"/django-admin/boxes/qrcode/{qr.pk}/change/", {"box": other.pk, "product": qr.product.pk, "note": ""}
    )
    assert response.status_code == 302
    qr.refresh_from_db()
    assert qr.box == other and not qr.is_active  # case « actif » décochée
    assert {"qr.reassign", "qr.deactivate"} <= set(AuditLog.objects.values_list("action", flat=True))


def test_actions_groupees(staff_client):
    qr = QRCodeFactory()
    staff_client.post(
        "/django-admin/boxes/qrcode/", {"action": "regenerate_qr_codes", "_selected_action": [qr.pk]}
    )
    qr.refresh_from_db()
    assert not qr.is_active and qr.replaced_by is not None
    response = staff_client.post(
        "/django-admin/boxes/qrcode/",
        {"action": "activate_qr_codes", "_selected_action": [qr.pk]},
        follow=True,
    )
    assert "remplacé" in response.content.decode()  # erreur métier affichée, pas d'exception


def test_suppression_desactivee(staff_client):
    qr = QRCodeFactory()
    assert staff_client.get(f"/django-admin/boxes/qrcode/{qr.pk}/delete/").status_code == 403
    assert staff_client.get(f"/django-admin/boxes/box/{qr.box.pk}/delete/").status_code == 403
