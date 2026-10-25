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


@pytest.fixture
def make_staff(db):
    """Fabrique de membres du personnel : make_staff("MARKETING", email=...)."""
    from apps.accounts.tests.factories import UserFactory

    def _make(*roles, **fields):
        return UserFactory(roles=list(roles), **fields)

    return _make


@pytest.fixture
def admin_api_client(make_staff):
    """Client authentifié par JWT avec le(s) rôle(s) demandé(s) : admin_api_client("MARKETING").

    (Nommé ainsi pour ne pas masquer la fixture `admin_client` fournie par pytest-django.)
    """
    from apps.accounts.tokens import issue_tokens

    def _client(*roles, **fields):
        user = make_staff(*roles, **fields)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user)['access']}")
        client.user = user
        return client

    return _client
