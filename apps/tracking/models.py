from django.db import models
from django.utils import timezone

from apps.boxes.models import Box, QRCode
from apps.catalog.models import Product, ProductVariant
from apps.core.choices import Channel

from .choices import EventType


class TrackingEventImmutableError(RuntimeError):
    """Un événement de traçabilité ne se modifie pas (seule la purge de rétention les supprime)."""


class TrackingEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TrackingEventImmutableError("Un événement de traçabilité ne peut pas être modifié.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TrackingEventImmutableError("Un événement de traçabilité ne peut pas être modifié.")


class TrackingEvent(models.Model):
    """Événement anonyme du tunnel (R08) : ni nom, ni téléphone, ni e-mail, ni IP, ni navigateur.

    box et product sont COPIÉS au moment de l'événement : une réaffectation ultérieure du QR ne
    change pas l'historique. Le lien vers la commande (order) est ajouté à l'étape 12.
    """

    id = models.BigAutoField(primary_key=True)
    event_type = models.CharField("type", max_length=30, choices=EventType.choices, db_index=True)
    occurred_at = models.DateTimeField("date (serveur)", default=timezone.now, db_index=True, editable=False)
    visitor_id = models.UUIDField("visiteur anonyme", db_index=True)
    channel = models.CharField("canal", max_length=10, choices=Channel.choices, default=Channel.UNKNOWN)
    qr = models.ForeignKey(
        QRCode,
        verbose_name="QR code",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tracking_events",
    )
    box = models.ForeignKey(
        Box,
        verbose_name="box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tracking_events",
    )
    product = models.ForeignKey(
        Product,
        verbose_name="produit",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tracking_events",
    )
    variant = models.ForeignKey(
        ProductVariant,
        verbose_name="variante",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tracking_events",
    )
    quantity = models.PositiveSmallIntegerField("quantité", null=True, blank=True)
    metadata = models.JSONField("métadonnées", default=dict, blank=True)

    objects = TrackingEventQuerySet.as_manager()

    class Meta:
        verbose_name = "événement de traçabilité"
        verbose_name_plural = "événements de traçabilité"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["box", "event_type", "occurred_at"], name="tracking_box_type_date_idx"),
            models.Index(
                fields=["product", "event_type", "occurred_at"], name="tracking_product_type_date_idx"
            ),
            models.Index(fields=["qr", "occurred_at"], name="tracking_qr_date_idx"),
            models.Index(fields=["visitor_id", "occurred_at"], name="tracking_visitor_date_idx"),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} — {self.occurred_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TrackingEventImmutableError("Un événement de traçabilité ne peut pas être modifié.")
        super().save(*args, **kwargs)
