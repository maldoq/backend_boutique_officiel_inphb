"""Journal des événements (admin) et purge de rétention."""

import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.capabilities import ROLE_CAPABILITIES, ROLES
from apps.boxes.tests.factories import QRCodeFactory
from apps.catalog.tests.factories import VariantFactory
from apps.tracking.models import TrackingEvent

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/tracking/events/"


def event(**fields):
    defaults = {"event_type": "product_view", "visitor_id": uuid.uuid4()}
    return TrackingEvent.objects.create(**{**defaults, **fields})


@pytest.mark.parametrize("role", list(ROLES))
def test_permissions(admin_api_client, role):
    status = admin_api_client(role).get(URL).status_code
    assert status == (200 if "tracking.view" in ROLE_CAPABILITIES[role] else 403)


def test_anonyme_401(api_client):
    assert api_client.get(URL).status_code == 401


def test_journal_filtres_et_visiteur_tronque(admin_api_client):
    client = admin_api_client("MARKETING")
    qr = QRCodeFactory()
    variant = VariantFactory(product=qr.product, size="M")
    visitor = uuid.UUID("c0a8f1e2-5b7d-4c11-9e0a-2f6d3b8a9c10")
    scan = event(
        event_type="qr_scan", visitor_id=visitor, qr=qr, box=qr.box, product=qr.product, channel="ios"
    )
    event(event_type="add_to_cart", qr=qr, box=qr.box, product=qr.product, variant=variant, quantity=2)
    event(event_type="checkout_started", channel="web")

    body = client.get(URL).json()
    assert body["count"] == 3
    item = next(row for row in body["results"] if row["id"] == scan.pk)
    assert item["visitor"] == "c0a8f1e2" and item["event_type_label"] == "Scan de QR code"
    assert item["box"]["code"] == qr.box.code and item["qr"]["code"] == qr.code
    assert client.get(URL, {"event_type": "add_to_cart"}).json()["results"][0]["variant"]["label"] == "M"
    assert client.get(URL, {"box": qr.box.pk}).json()["count"] == 2
    assert client.get(URL, {"channel": "ios"}).json()["count"] == 1
    today = timezone.localdate().isoformat()
    assert client.get(URL, {"date_from": today, "date_to": today}).json()["count"] == 3
    assert client.get(URL, {"date_from": "2026-12-31", "date_to": "2026-01-01"}).status_code == 400
    assert client.get(URL, {"event_type": "inconnu"}).status_code == 400


def test_journal_nombre_de_requetes_constant(admin_api_client):
    client = admin_api_client("STATS_AUDIT")

    def count():
        with CaptureQueriesContext(connection) as context:
            assert client.get(URL).status_code == 200
        return len(context.captured_queries)

    qr = QRCodeFactory()
    for _ in range(2):
        event(qr=qr, box=qr.box, product=qr.product)
    few = count()
    for _ in range(10):
        other = QRCodeFactory()
        event(qr=other, box=other.box, product=other.product)
    assert count() == few


# --- Purge de rétention -----------------------------------------------------------------------


def test_purge_supprime_seulement_les_evenements_expires(capsys):
    now = timezone.now()
    with freeze_time(now - timedelta(days=800)):
        old = [event() for _ in range(3)]
    with freeze_time(now - timedelta(days=700)):
        recent = event()
    call_command("purge_tracking", "--batch-size", "2")
    assert set(TrackingEvent.objects.values_list("id", flat=True)) == {recent.pk}
    assert "3 événement(s)" in capsys.readouterr().out
    assert not TrackingEvent.objects.filter(pk__in=[e.pk for e in old]).exists()


def test_purge_simulation_et_duree_personnalisee(capsys):
    with freeze_time(timezone.now() - timedelta(days=40)):
        event()
    call_command("purge_tracking", "--days", "30", "--dry-run")
    assert "1 événement(s)" in capsys.readouterr().out
    assert TrackingEvent.objects.count() == 1
    call_command("purge_tracking", "--days", "30")
    assert TrackingEvent.objects.count() == 0


@pytest.mark.parametrize("args", [["--days", "0"], ["--batch-size", "0"]])
def test_purge_parametres_invalides(args):
    with pytest.raises(CommandError):
        call_command("purge_tracking", *args)
