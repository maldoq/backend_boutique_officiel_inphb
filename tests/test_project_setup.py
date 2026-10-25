"""Étape 1 : configuration Django, applications et routes racines."""

import importlib

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model

LOCAL_APPS = [
    "core",
    "accounts",
    "audit",
    "catalog",
    "inventory",
    "boxes",
    "tracking",
    "orders",
    "payments",
    "notifications",
    "analytics",
]


@pytest.mark.parametrize("label", LOCAL_APPS)
def test_app_declaree_et_importable(label):
    config = apps.get_app_config(label)
    assert config.name == f"apps.{label}"
    importlib.import_module(config.name)


def test_reglages_metier_et_regionaux():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert settings.TIME_ZONE == "Africa/Abidjan"
    assert settings.LANGUAGE_CODE == "fr"
    assert settings.USE_TZ is True
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]
    assert "x-visitor-id" in settings.CORS_ALLOW_HEADERS
    assert settings.CORS_EXPOSE_HEADERS == ["X-Visitor-Id"]


@pytest.mark.django_db
def test_schema_openapi_accessible(api_client):
    response = api_client.get("/api/schema/")
    assert response.status_code == 200
    assert b"API Boutique INP-HB" in response.content


@pytest.mark.django_db
def test_swagger_accessible(api_client):
    response = api_client.get("/api/docs/")
    assert response.status_code == 200
    assert b"swagger" in response.content.lower()


def test_django_admin_monte_sur_url_dediee():
    assert settings.DJANGO_ADMIN_URL == "django-admin/"


@pytest.mark.django_db
def test_django_admin_redirige_vers_connexion(client):
    response = client.get("/django-admin/")
    assert response.status_code == 302
    assert "/django-admin/login/" in response["Location"]


@pytest.mark.django_db
def test_utilisateur_email_en_minuscules_sans_username():
    user = get_user_model().objects.create_user(email="Agent.Boutique@Exemple.CI", password="x" * 12)
    assert user.email == "agent.boutique@exemple.ci"
    assert not hasattr(user, "username") or user.username is None
    assert get_user_model().objects.get_by_natural_key("AGENT.boutique@exemple.ci") == user


@pytest.mark.django_db
def test_superutilisateur():
    admin = get_user_model().objects.create_superuser(email="admin@exemple.ci", password="x" * 12)
    assert admin.is_staff and admin.is_superuser
