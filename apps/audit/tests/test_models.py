"""Le journal d'audit est inaltérable (R14)."""

import pytest

from apps.audit.models import AuditLog, AuditLogImmutableError
from apps.audit.services import log_action
from apps.core.models import SiteSettings


@pytest.fixture
def entry(make_staff):
    return log_action(
        actor=make_staff(email="agent@exemple.ci"),
        action="settings.update",
        obj=SiteSettings.load(),
        changes={"maintenance_mode": [False, True]},
    )


@pytest.mark.django_db
def test_modification_refusee(entry):
    entry.action = "settings.delete"
    with pytest.raises(AuditLogImmutableError):
        entry.save()
    entry.refresh_from_db()
    assert entry.action == "settings.update"


@pytest.mark.django_db
def test_suppression_refusee(entry):
    with pytest.raises(AuditLogImmutableError):
        entry.delete()
    assert AuditLog.objects.count() == 1


@pytest.mark.django_db
def test_modification_et_suppression_en_masse_refusees(entry):
    with pytest.raises(AuditLogImmutableError):
        AuditLog.objects.update(action="settings.delete")
    with pytest.raises(AuditLogImmutableError):
        AuditLog.objects.filter(pk=entry.pk).delete()
    with pytest.raises(AuditLogImmutableError):
        AuditLog.objects.bulk_update([entry], ["action"])
    assert AuditLog.objects.get().action == "settings.update"


@pytest.mark.django_db
def test_suppression_de_l_auteur_conserve_la_trace(entry):
    entry.actor.delete()
    entry.refresh_from_db()
    assert entry.actor is None
    assert entry.actor_email == "agent@exemple.ci"


@pytest.mark.django_db
def test_ordre_du_plus_recent_au_plus_ancien(make_staff):
    site = SiteSettings.load()
    first = log_action(actor=None, action="settings.update", obj=site)
    second = log_action(actor=None, action="settings.update", obj=site)
    assert list(AuditLog.objects.all()) == [second, first]
