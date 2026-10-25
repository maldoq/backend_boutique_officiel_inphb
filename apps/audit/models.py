from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimeStampedModel

ACTION_REGEX = r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$"


class AuditLogImmutableError(RuntimeError):
    """Le journal d'audit ne se modifie ni ne se supprime (R14)."""


class AuditLogQuerySet(models.QuerySet):
    """Bloque aussi les modifications et suppressions en masse."""

    def update(self, **kwargs):
        raise AuditLogImmutableError("Les entrées du journal d'audit ne peuvent pas être modifiées.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditLogImmutableError("Les entrées du journal d'audit ne peuvent pas être modifiées.")

    def delete(self):
        raise AuditLogImmutableError("Les entrées du journal d'audit ne peuvent pas être supprimées.")


class AuditLog(TimeStampedModel):
    """Trace d'une opération sensible. Écrite uniquement via apps.audit.services.log_action()."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    actor_email = models.CharField("e-mail de l'auteur", max_length=254, blank=True)
    action = models.CharField(
        "action", max_length=60, db_index=True, validators=[RegexValidator(ACTION_REGEX)]
    )
    object_type = models.CharField("type d'objet", max_length=100)
    object_id = models.CharField("identifiant de l'objet", max_length=64)
    object_repr = models.CharField("objet", max_length=200)
    changes = models.JSONField("modifications", default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField("adresse IP", null=True, blank=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["actor", "created_at"], name="audit_actor_created_idx"),
        ]

    def __str__(self):
        return f"{self.action} — {self.object_repr} ({self.actor_email or 'système'})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutableError("Les entrées du journal d'audit ne peuvent pas être modifiées.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutableError("Les entrées du journal d'audit ne peuvent pas être supprimées.")
