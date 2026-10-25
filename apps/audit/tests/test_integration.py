"""Opérations sensibles déjà existantes : elles doivent toutes laisser une trace."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.tests.factories import TEST_PASSWORD
from apps.audit.models import AuditLog
from apps.audit.viewsets import AdminAPIView, AdminModelViewSet, AdminViewSet
from apps.core.models import SiteSettings


@pytest.fixture
def superuser_client(client, make_staff):
    admin = make_staff(email="root@exemple.ci", is_superuser=True)
    client.force_login(admin)
    client.admin = admin
    return client


# --- Vues d'administration auditables ------------------------------------------


def test_bases_auditables_pour_les_apps_metier():
    for base in (AdminAPIView, AdminViewSet, AdminModelViewSet):
        assert hasattr(base, "audit")


@pytest.mark.django_db
def test_self_audit_depuis_une_vue(make_staff):
    class SettingsView(AdminAPIView):
        required_capabilities = {"*": "settings.manage"}

        def post(self, request):
            entry = self.audit("settings.update", SiteSettings.load(), {"slogan": ["A", "B"]})
            return Response({"id": entry.pk})

    agent = make_staff("RESPONSABLE_BOUTIQUE", email="resp@exemple.ci")
    request = APIRequestFactory().post("/api/v1/admin/settings/", REMOTE_ADDR="192.168.1.30")
    force_authenticate(request, user=agent)
    response = SettingsView.as_view()(request)

    assert response.status_code == 200
    entry = AuditLog.objects.get(pk=response.data["id"])
    assert (entry.actor, entry.ip_address, entry.changes) == (agent, "192.168.1.30", {"slogan": ["A", "B"]})


# --- Changement de mot de passe (API) ------------------------------------------


@pytest.mark.django_db
def test_changement_de_mot_de_passe_audite_sans_secret(admin_api_client):
    client = admin_api_client("ADMIN_GENERAL", must_change_password=True)
    response = client.post(
        "/api/v1/admin/auth/change-password/",
        {"current_password": TEST_PASSWORD, "new_password": "Nouveau-Secret-2026"},
        format="json",
        REMOTE_ADDR="192.168.1.40",
    )
    assert response.status_code == 200

    entry = AuditLog.objects.get(action="user.password_change")
    assert entry.actor == client.user
    assert entry.object_id == str(client.user.pk)
    assert entry.ip_address == "192.168.1.40"
    assert entry.changes["must_change_password"] == [True, False]
    serialized = str(entry.changes)
    assert "Nouveau-Secret-2026" not in serialized and TEST_PASSWORD not in serialized
    assert "pbkdf2" not in serialized and "md5" not in serialized


@pytest.mark.django_db
def test_changement_de_mot_de_passe_refuse_non_audite(admin_api_client):
    client = admin_api_client("ADMIN_GENERAL")
    client.post(
        "/api/v1/admin/auth/change-password/",
        {"current_password": "faux", "new_password": "Nouveau-Secret-2026"},
        format="json",
    )
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_connexion_non_auditee(api_client, make_staff):
    make_staff(email="agent@exemple.ci")
    api_client.post(
        "/api/v1/admin/auth/login/", {"email": "agent@exemple.ci", "password": TEST_PASSWORD}, format="json"
    )
    assert not AuditLog.objects.exists()  # connexions : journaux applicatifs, pas l'audit


# --- Django Admin (secours technique) ------------------------------------------


@pytest.mark.django_db
def test_creation_de_compte_dans_django_admin_auditee(superuser_client):
    superuser_client.post(
        "/django-admin/accounts/user/add/",
        {
            "email": "nouvel.agent@exemple.ci",
            "first_name": "Kouamé",
            "last_name": "Yao",
            "usable_password": "true",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    entry = AuditLog.objects.get(action="user.create")
    assert entry.actor == superuser_client.admin
    assert entry.object_repr == "nouvel.agent@exemple.ci"
    assert entry.changes["must_change_password"] == [None, True]
    assert "password" not in entry.changes


def _change_form_data(user, **overrides):
    data = {
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "is_active": "on" if user.is_active else "",
        "is_staff": "on" if user.is_staff else "",
        "groups": [group.pk for group in user.groups.all()],
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value not in ("", None)}


@pytest.mark.django_db
def test_changement_de_role_dans_django_admin_audite(superuser_client, make_staff):
    agent = make_staff("GESTIONNAIRE_CATALOGUE", email="agent@exemple.ci")
    marketing = Group.objects.create(name="MARKETING")
    catalogue = Group.objects.get(name="GESTIONNAIRE_CATALOGUE")

    response = superuser_client.post(
        f"/django-admin/accounts/user/{agent.pk}/change/",
        _change_form_data(agent, groups=[catalogue.pk, marketing.pk]),
    )
    assert response.status_code == 302, response.content

    entry = AuditLog.objects.get(action="user.role_change")
    assert entry.changes == {"roles": [["GESTIONNAIRE_CATALOGUE"], ["GESTIONNAIRE_CATALOGUE", "MARKETING"]]}
    assert entry.actor == superuser_client.admin
    assert not AuditLog.objects.filter(action="user.update").exists()


@pytest.mark.django_db
def test_desactivation_dans_django_admin_auditee(superuser_client, make_staff):
    agent = make_staff(email="agent@exemple.ci")
    superuser_client.post(
        f"/django-admin/accounts/user/{agent.pk}/change/", _change_form_data(agent, is_active="")
    )
    entry = AuditLog.objects.get(action="user.update")
    assert entry.changes == {"is_active": [True, False]}


@pytest.mark.django_db
def test_mot_de_passe_defini_par_un_administrateur(superuser_client, make_staff):
    agent = make_staff(email="agent@exemple.ci")
    response = superuser_client.post(
        f"/django-admin/accounts/user/{agent.pk}/password/",
        {"usable_password": "true", "password1": "Temporaire-2026-X", "password2": "Temporaire-2026-X"},
    )
    assert response.status_code == 302, response.content
    agent.refresh_from_db()
    assert agent.must_change_password is True  # mot de passe temporaire
    entry = AuditLog.objects.get(action="user.password_reset")
    assert "Temporaire-2026-X" not in str(entry.changes)


@pytest.mark.django_db
def test_parametres_modifies_dans_django_admin_audites(superuser_client):
    site = SiteSettings.load()
    response = superuser_client.post(
        f"/django-admin/core/sitesettings/{site.pk}/change/",
        {
            "shop_name": site.shop_name,
            "slogan": site.slogan,
            "contact_phone": "07 00 00 00 00",
            "contact_email": "",
            "default_low_stock_threshold": site.default_low_stock_threshold,
            "pickup_hold_days": site.pickup_hold_days,
            "order_confirmation_message": "",
            "maintenance_mode": "on",
        },
    )
    assert response.status_code == 302, response.content
    entry = AuditLog.objects.get(action="settings.update")
    assert entry.changes == {
        "contact_phone": ["", "+2250700000000"],
        "maintenance_mode": [False, True],
    }


@pytest.mark.django_db
def test_journal_en_lecture_seule_dans_django_admin(superuser_client):
    entry = AuditLog.objects.create(
        action="settings.update", object_type="core.SiteSettings", object_id="1", object_repr="x"
    )
    assert superuser_client.get("/django-admin/audit/auditlog/").status_code == 200
    assert superuser_client.get(f"/django-admin/audit/auditlog/{entry.pk}/change/").status_code == 200
    assert superuser_client.get("/django-admin/audit/auditlog/add/").status_code == 403
    assert superuser_client.post(f"/django-admin/audit/auditlog/{entry.pk}/change/", {}).status_code == 403
    assert (
        superuser_client.post(f"/django-admin/audit/auditlog/{entry.pk}/delete/", {"post": "yes"}).status_code
        == 403
    )
    assert AuditLog.objects.filter(pk=entry.pk).exists()


@pytest.mark.django_db
def test_utilisateur_supprime_dans_django_admin_trace_conservee(superuser_client, make_staff):
    agent = make_staff(email="agent@exemple.ci")
    AuditLog.objects.create(
        actor=agent,
        actor_email=agent.email,
        action="settings.update",
        object_type="core.SiteSettings",
        object_id="1",
        object_repr="x",
    )
    get_user_model().objects.filter(pk=agent.pk).delete()
    entry = AuditLog.objects.get()
    assert entry.actor is None and entry.actor_email == "agent@exemple.ci"
