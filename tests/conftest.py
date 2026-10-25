import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    """Client HTTP anonyme (site web / application mobile)."""
    return APIClient()
