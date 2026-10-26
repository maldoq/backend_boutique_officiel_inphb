from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import ProductVariant
from apps.core.models import TimeStampedModel

from .choices import StockReason


class StockMovementImmutableError(RuntimeError):
    """L'historique des mouvements de stock ne se modifie ni ne se supprime."""


class StockMovementQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise StockMovementImmutableError("Un mouvement de stock ne peut pas être modifié.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise StockMovementImmutableError("Un mouvement de stock ne peut pas être modifié.")

    def delete(self):
        raise StockMovementImmutableError("Un mouvement de stock ne peut pas être supprimé.")


class StockMovement(TimeStampedModel):
    """Historique de chaque variation de stock. Créé uniquement par apps.inventory.services."""

    variant = models.ForeignKey(
        ProductVariant, verbose_name="variante", on_delete=models.PROTECT, related_name="stock_movements"
    )
    delta = models.IntegerField("variation", help_text="Positif : entrée ; négatif : sortie.")
    reason = models.CharField("motif", max_length=30, choices=StockReason.choices)
    balance_after = models.PositiveIntegerField("stock après mouvement")
    # Le lien vers la commande (order) est ajouté à l'étape 12 : `orders` vient après `inventory` (C.2).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Vide : opération du système.",
    )
    note = models.CharField("note", max_length=255, blank=True)

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(delta=0), name="inventory_movement_delta_not_zero"),
            models.CheckConstraint(
                condition=Q(balance_after__gte=0), name="inventory_movement_balance_non_negative"
            ),
        ]
        indexes = [
            models.Index(fields=["variant", "created_at"], name="inventory_variant_created_idx"),
            models.Index(fields=["reason", "created_at"], name="inventory_reason_created_idx"),
        ]

    def __str__(self):
        return f"{self.delta:+d} {self.variant} ({self.get_reason_display()})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise StockMovementImmutableError("Un mouvement de stock ne peut pas être modifié.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise StockMovementImmutableError("Un mouvement de stock ne peut pas être supprimé.")
