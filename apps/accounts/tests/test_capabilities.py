"""La matrice des rôles doit correspondre exactement au tableau C.6 de la spécification."""

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command

from apps.accounts.capabilities import (
    ALL_CAPABILITIES,
    ROLE_CAPABILITIES,
    ROLES,
    admin_caps,
    user_capabilities,
    user_roles,
)

ROLE_COLUMNS = [
    "ADMIN_GENERAL",
    "RESPONSABLE_BOUTIQUE",
    "GESTIONNAIRE_CATALOGUE",
    "GESTIONNAIRE_COMMANDES",
    "MARKETING",
    "STATS_AUDIT",
]

# Recopie indépendante du tableau C.6 (une ligne par capacité, une colonne par rôle).
C6_MATRIX = {
    "catalog.view": "111111",
    "catalog.manage": "111000",
    "stock.view": "111101",
    "stock.manage": "111000",
    "orders.view": "110101",
    "orders.manage": "110100",
    "pickup.manage": "110000",
    "boxes.view": "110011",
    "boxes.manage": "110010",
    "tracking.view": "110011",
    "analytics.view": "110011",
    "analytics.export": "110011",
    "promotions.manage": "110010",
    "content.manage": "110010",
    "payments.view": "110101",
    "users.manage": "100000",
    "audit.view": "110001",
    "settings.manage": "110000",
}


def test_matrice_identique_au_tableau_c6():
    assert set(C6_MATRIX) == set(ALL_CAPABILITIES)
    assert list(ROLES) == ROLE_COLUMNS
    for capability, row in C6_MATRIX.items():
        for role, allowed in zip(ROLE_COLUMNS, row, strict=True):
            assert (capability in ROLE_CAPABILITIES[role]) is (allowed == "1"), (role, capability)


@pytest.mark.django_db
def test_union_des_roles(make_staff):
    user = make_staff("GESTIONNAIRE_CATALOGUE", "MARKETING")
    assert user_roles(user) == ["GESTIONNAIRE_CATALOGUE", "MARKETING"]
    assert (
        user_capabilities(user)
        == ROLE_CAPABILITIES["GESTIONNAIRE_CATALOGUE"] | ROLE_CAPABILITIES["MARKETING"]
    )


@pytest.mark.django_db
def test_superutilisateur_a_toutes_les_capacites(make_staff):
    assert user_capabilities(make_staff(is_superuser=True)) == frozenset(ALL_CAPABILITIES)


@pytest.mark.django_db
def test_sans_role_aucune_capacite_et_groupe_inconnu_ignore(make_staff):
    user = make_staff()
    user.groups.add(Group.objects.create(name="GROUPE_LIBRE"))
    assert user_roles(user) == []
    assert user_capabilities(user) == frozenset()


@pytest.mark.django_db
def test_compte_inactif_ou_anonyme_sans_capacite(make_staff):
    assert user_capabilities(make_staff("ADMIN_GENERAL", is_active=False)) == frozenset()
    assert user_capabilities(AnonymousUser()) == frozenset()


def test_admin_caps():
    caps = admin_caps("catalog.view", "catalog.manage")
    assert caps["GET"] == caps["HEAD"] == caps["OPTIONS"] == "catalog.view"
    assert caps["POST"] == caps["PUT"] == caps["PATCH"] == caps["DELETE"] == "catalog.manage"
    with pytest.raises(ValueError):
        admin_caps("catalog.view", "inconnue.manage")


@pytest.mark.django_db
def test_setup_roles_idempotent():
    call_command("setup_roles", stdout=None)
    call_command("setup_roles", stdout=None)
    assert sorted(Group.objects.values_list("name", flat=True)) == sorted(ROLE_COLUMNS)
