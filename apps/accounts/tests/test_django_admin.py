"""Django Admin (secours technique) : création d'un compte du personnel par e-mail."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.tests.factories import TEST_PASSWORD


@pytest.fixture
def superuser_client(client, make_staff):
    client.force_login(make_staff(email="root@exemple.ci", is_superuser=True))
    return client


@pytest.mark.django_db
def test_liste_et_formulaires_s_affichent(superuser_client, make_staff):
    user = make_staff("MARKETING")
    assert superuser_client.get("/django-admin/accounts/user/").status_code == 200
    assert superuser_client.get("/django-admin/accounts/user/add/").status_code == 200
    assert superuser_client.get(f"/django-admin/accounts/user/{user.pk}/change/").status_code == 200


@pytest.mark.django_db
def test_creation_par_un_administrateur_impose_le_changement_de_mot_de_passe(superuser_client):
    response = superuser_client.post(
        "/django-admin/accounts/user/add/",
        {
            "email": "Nouvel.Agent@Exemple.CI",
            "first_name": "Kouamé",
            "last_name": "Yao",
            "usable_password": "true",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert response.status_code == 302, response.content
    user = get_user_model().objects.get(email="nouvel.agent@exemple.ci")
    assert user.is_staff and user.must_change_password
    assert user.check_password(TEST_PASSWORD)


@pytest.mark.django_db
def test_email_en_double_refuse(superuser_client, make_staff):
    make_staff(email="agent@exemple.ci")
    response = superuser_client.post(
        "/django-admin/accounts/user/add/",
        {
            "email": "AGENT@exemple.ci",
            "usable_password": "true",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert response.status_code == 200
    assert "existe déjà" in response.content.decode()


@pytest.mark.django_db
def test_groupes_de_roles_attribuables(superuser_client, make_staff):
    Group.objects.create(name="MARKETING")
    assert superuser_client.get("/django-admin/auth/group/").status_code == 200
