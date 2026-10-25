"""Fixtures pytest globales, visibles par les tests de apps/*/tests/ et de tests/.

(À la racine et non dans tests/ : un conftest.py ne s'applique qu'à son propre dossier.)
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    """Client HTTP anonyme (site web / application mobile)."""
    return APIClient()


@pytest.fixture(autouse=True)
def _isolated_cache():
    """Cache vidé entre les tests (compteurs de throttling, etc.)."""
    cache.clear()
    yield
    cache.clear()
