import datetime
import decimal
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.db import transaction
from django.test import RequestFactory, override_settings

from apps.audit.models import AuditLog
from apps.audit.services import MASKED, diff_instance, log_action, normalize_changes, to_audit_value
from apps.core.models import SiteSettings


@pytest.fixture
def site():
    return SiteSettings.load()


@pytest.mark.django_db
def test_log_action_entree_complete(make_staff, site):
    agent = make_staff("RESPONSABLE_BOUTIQUE", email="resp@exemple.ci")
    request = RequestFactory().post("/api/v1/admin/settings/", REMOTE_ADDR="192.168.1.20")

    entry = log_action(
        actor=agent,
        action="settings.update",
        obj=site,
        changes={"maintenance_mode": [False, True]},
        request=request,
    )

    entry.refresh_from_db()
    assert entry.actor == agent
    assert entry.actor_email == "resp@exemple.ci"
    assert entry.action == "settings.update"
    assert entry.object_type == "core.SiteSettings"
    assert entry.object_id == "1"
    assert entry.object_repr == "Boutique INP-HB"
    assert entry.changes == {"maintenance_mode": [False, True]}
    assert entry.ip_address == "192.168.1.20"
    assert entry.created_at is not None


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={"NUM_PROXIES": 1})
def test_ip_reelle_derriere_un_proxy(make_staff, site):
    from rest_framework.settings import api_settings

    api_settings.reload()
    try:
        request = RequestFactory().post(
            "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="41.207.1.2, 10.0.0.1"
        )
        entry = log_action(actor=make_staff(), action="settings.update", obj=site, request=request)
        assert entry.ip_address == "10.0.0.1"
        # NUM_PROXIES=1 : on prend l'adresse ajoutée par Nginx (dernière), pas celle choisie par le client.
    finally:
        api_settings.reload()


@pytest.mark.django_db
def test_action_systeme_ou_anonyme_sans_auteur_ni_ip(site):
    request = RequestFactory().post("/", REMOTE_ADDR="192.168.1.20")
    for actor in (None, AnonymousUser()):
        entry = log_action(actor=actor, action="settings.update", obj=site, request=request)
        assert entry.actor is None
        assert entry.actor_email == ""
        assert entry.ip_address is None


@pytest.mark.django_db
def test_pas_d_ip_pour_un_compte_hors_personnel(make_staff, site):
    customer = make_staff(is_staff=False)  # futur client (Phase 2)
    request = RequestFactory().post("/", REMOTE_ADDR="192.168.1.20")
    entry = log_action(actor=customer, action="settings.update", obj=site, request=request)
    assert entry.actor == customer
    assert entry.ip_address is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action", ["", "update", "Product.Update", "product.", "produit mis à jour", "x" * 61]
)
def test_action_mal_formee_refusee(site, action):
    with pytest.raises(ValueError):
        log_action(actor=None, action=action, obj=site)
    assert AuditLog.objects.count() == 0


@pytest.mark.django_db
def test_objet_non_enregistre_refuse():
    with pytest.raises(ValueError):
        log_action(actor=None, action="group.create", obj=Group(name="X"))


@pytest.mark.django_db
def test_representation_tronquee_a_100_caracteres(site):
    site.shop_name = "B" * 120
    site.save()
    entry = log_action(actor=None, action="settings.update", obj=site)
    assert len(entry.object_repr) == 100


@pytest.mark.django_db
def test_rollback_de_l_operation_annule_la_trace(site):
    with pytest.raises(RuntimeError), transaction.atomic():
        log_action(actor=None, action="settings.update", obj=site)
        raise RuntimeError("échec de l'opération auditée")
    assert AuditLog.objects.count() == 0


@pytest.mark.django_db
def test_diff_instance_seulement_les_champs_modifies(site):
    changes = diff_instance(
        site,
        {"shop_name": "Boutique INP-HB", "maintenance_mode": True, "pickup_hold_days": 10},
        fields=["shop_name", "maintenance_mode", "pickup_hold_days", "slogan"],
    )
    assert changes == {"maintenance_mode": [False, True], "pickup_hold_days": [7, 10]}


@pytest.mark.django_db
def test_diff_instance_sans_liste_de_champs_et_objet_lie(make_staff):
    user = make_staff(email="a@exemple.ci")
    entry_owner = make_staff(email="b@exemple.ci")
    entry = log_action(actor=user, action="settings.update", obj=SiteSettings.load())
    assert diff_instance(entry, {"actor": user}) == {}
    assert diff_instance(entry, {"actor": entry_owner}) == {
        "actor": [{"id": user.pk, "repr": "a@exemple.ci"}, {"id": entry_owner.pk, "repr": "b@exemple.ci"}]
    }


@pytest.mark.django_db
def test_mots_de_passe_et_secrets_masques(make_staff):
    user = make_staff()
    changes = diff_instance(user, {"password": "pbkdf2_sha256$nouveau-hachage"})
    assert changes == {"password": [MASKED, MASKED]}
    assert normalize_changes(
        {"api_key": ["ancienne", "nouvelle"], "webhook_secret": [None, "x"], "refresh_token": ["a", "b"]}
    ) == {"api_key": [MASKED, MASKED], "webhook_secret": [MASKED, MASKED], "refresh_token": [MASKED, MASKED]}


def test_indicateur_booleen_jamais_masque():
    assert normalize_changes({"must_change_password": [True, False]}) == {
        "must_change_password": [True, False]
    }
    assert normalize_changes({"password_hint": ["a", "b"]}) == {"password_hint": [MASKED, MASKED]}


@pytest.mark.django_db
def test_conversion_des_valeurs_en_json(make_staff):
    user = make_staff(email="a@exemple.ci")
    group = Group.objects.create(name="MARKETING")
    user.groups.add(group)
    moment = datetime.datetime(2026, 10, 24, 10, 15, 3, tzinfo=datetime.UTC)
    identifier = uuid.UUID("9b2f6c1e-1111-4222-8333-444455556666")

    assert to_audit_value(decimal.Decimal("12000.50")) == "12000.50"
    assert to_audit_value(moment) == "2026-10-24T10:15:03+00:00"
    assert to_audit_value(datetime.date(2026, 10, 24)) == "2026-10-24"
    assert to_audit_value(identifier) == "9b2f6c1e-1111-4222-8333-444455556666"
    assert to_audit_value(user) == {"id": user.pk, "repr": "a@exemple.ci"}
    assert to_audit_value(user.groups) == [{"id": group.pk, "repr": "MARKETING"}]
    assert to_audit_value({"b", "a"}) == ["a", "b"]
    assert to_audit_value(("x", 1)) == ["x", 1]

    entry = log_action(
        actor=user,
        action="settings.update",
        obj=SiteSettings.load(),
        changes={"quand": [None, moment], "montant": [decimal.Decimal("1"), decimal.Decimal("2")]},
    )
    entry.refresh_from_db()
    assert entry.changes == {"quand": [None, "2026-10-24T10:15:03+00:00"], "montant": ["1", "2"]}
