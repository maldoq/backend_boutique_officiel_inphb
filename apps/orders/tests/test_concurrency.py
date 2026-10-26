"""Deux commandes simultanées sur le dernier article : une seule réussit (R04, critère de l'étape 13).

Nécessite PostgreSQL (verrous de ligne réels, connexions parallèles) ; ignoré sous SQLite.
"""

import threading
import uuid

import pytest
from django.db import connection, connections

from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import VariantFactory
from apps.core.exceptions import InsufficientStock
from apps.orders.models import Order, PickupPoint
from apps.orders.services import create_order

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Test de concurrence : PostgreSQL requis."),
]


def test_dernier_article_commande_une_seule_fois():
    variant = VariantFactory(stock_quantity=1)
    point = PickupPoint.objects.get(code="BOUTIQUE-CENTRE")
    payload = {
        "customer": {"first_name": "Awa", "last_name": "Koné", "phone": "+2250700000000", "email": ""},
        "pickup_point_id": point.pk,
        "items": [{"variant_id": variant.pk, "quantity": 1}],
        "customer_note": "",
        "accept_terms": False,
    }
    barrier, outcomes = threading.Barrier(2), []

    def order():
        try:
            barrier.wait()
            create_order(payload=payload, channel="web", visitor_id=uuid.uuid4())
            outcomes.append("ok")
        except InsufficientStock:
            outcomes.append("refusé")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=order) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ok", "refusé"]
    assert Order.objects.count() == 1
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 0
