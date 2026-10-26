"""Deux réservations simultanées du dernier article : une seule réussit (R04).

Nécessite PostgreSQL (verrous de ligne réels, connexions parallèles). Ignoré sous SQLite, où la
requête conditionnelle du service reste sûre car SQLite sérialise toutes les écritures.
"""

import threading

import pytest
from django.db import connection, connections, transaction

from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import VariantFactory
from apps.core.exceptions import InsufficientStock
from apps.inventory.choices import StockReason
from apps.inventory.models import StockMovement
from apps.inventory.services import apply_movement

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Test de concurrence : PostgreSQL requis."),
]


def test_dernier_article_reserve_une_seule_fois():
    variant = VariantFactory(stock_quantity=1)
    barrier = threading.Barrier(2)
    outcomes = []

    def reserve():
        try:
            barrier.wait()
            with transaction.atomic():
                locked = ProductVariant.objects.select_for_update().get(pk=variant.pk)
                apply_movement(variant=locked, delta=-1, reason=StockReason.ORDER_RESERVED)
            outcomes.append("ok")
        except InsufficientStock:
            outcomes.append("refusé")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ok", "refusé"]
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 0
    assert StockMovement.objects.count() == 1
