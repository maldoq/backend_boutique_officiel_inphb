"""Commandes (invitées au MVP), lignes avec attribution, historique des statuts, points de retrait.

Garanties en base : montants cohérents (R01, R15), statut et paiement séparés (R02, R03), attribution
par ligne cohérente (R09), dates et motif obligatoires selon le statut. Une commande ne se supprime
jamais (D.4) ; son historique de statuts est inaltérable.
"""

import uuid

from django.conf import settings
from django.core.validators import MaxLengthValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

from apps.boxes.models import Box, QRCode
from apps.catalog.models import Product, ProductVariant
from apps.core.choices import Channel
from apps.core.models import TimeStampedModel
from apps.core.phone import InvalidPhoneNumber, normalize_phone, validate_phone

from .choices import FulfillmentMethod, OrderStatus, PaymentStatus

PICKUP_CODE_VALIDATOR = RegexValidator(r"^[A-Z0-9]+(-[A-Z0-9]+)*$", "Majuscules, chiffres et tirets.")
CUSTOMER_NOTE_MAX_LENGTH = 500


class DeletionForbidden(RuntimeError):
    """Une commande et son historique ne se suppriment pas (D.4) : on annule, et plus tard on anonymise."""


def _normalized_phone(value: str) -> str:
    try:
        return normalize_phone(value) if value else value
    except InvalidPhoneNumber:
        return value  # laissé tel quel : le validateur du champ produira l'erreur


class PickupPoint(TimeStampedModel):
    """Point de retrait Click & Collect activable par l'INP-HB."""

    code = models.CharField(
        "code",
        max_length=40,
        unique=True,
        validators=[PICKUP_CODE_VALIDATOR],
        help_text="Ex. BOUTIQUE-CENTRE",
    )
    name = models.CharField("nom", max_length=120)
    address = models.CharField("adresse", max_length=255, blank=True)
    instructions = models.TextField("instructions de retrait", blank=True)
    opening_hours = models.CharField("horaires", max_length=255, blank=True)
    phone = models.CharField("téléphone", max_length=20, blank=True, validators=[validate_phone])
    is_active = models.BooleanField("actif", default=True)
    position = models.PositiveSmallIntegerField("position", default=0)

    class Meta:
        verbose_name = "point de retrait"
        verbose_name_plural = "points de retrait"
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    def _normalize(self):
        self.code = "-".join((self.code or "").split()).upper()
        self.phone = _normalized_phone(self.phone)

    def clean_fields(self, exclude=None):
        self._normalize()
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self._normalize()
        super().save(*args, **kwargs)


class OrderQuerySet(models.QuerySet):
    def delete(self):
        raise DeletionForbidden("Une commande ne peut pas être supprimée : annulez-la.")


class Order(TimeStampedModel):
    """Commande invitée Click & Collect. Montants calculés par le serveur uniquement (R01)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # jamais exposé au public
    public_reference = models.CharField("référence", max_length=16, unique=True, editable=False)
    status = models.CharField(
        "statut", max_length=30, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True
    )
    payment_status = models.CharField(
        "paiement", max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True
    )
    fulfillment_method = models.CharField(
        "mode de retrait",
        max_length=30,
        choices=FulfillmentMethod.choices,
        default=FulfillmentMethod.CLICK_AND_COLLECT,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="compte client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )  # Phase 2
    customer_first_name = models.CharField("prénom", max_length=80)
    customer_last_name = models.CharField("nom", max_length=80)
    customer_phone = models.CharField("téléphone", max_length=20, validators=[validate_phone])
    customer_email = models.EmailField("e-mail", blank=True)
    pickup_point = models.ForeignKey(
        PickupPoint,
        verbose_name="point de retrait",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    pickup_code = models.CharField("code de retrait", max_length=8, unique=True, editable=False)
    subtotal_xof = models.PositiveIntegerField("sous-total (XOF)", default=0)
    discount_xof = models.PositiveIntegerField("remise (XOF)", default=0)
    shipping_fee_xof = models.PositiveIntegerField("frais (XOF)", default=0)
    total_xof = models.PositiveIntegerField("total (XOF)", default=0)
    currency = models.CharField("devise", max_length=3, default="XOF", editable=False)
    channel = models.CharField("canal", max_length=10, choices=Channel.choices, default=Channel.UNKNOWN)
    visitor_id = models.UUIDField("visiteur anonyme", null=True, blank=True)
    # Raccourcis : source de la première ligne attribuée (l'analyse se fait sur les lignes, R09).
    source_box = models.ForeignKey(
        Box, verbose_name="box source", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_qr = models.ForeignKey(
        QRCode, verbose_name="QR source", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    customer_note = models.TextField(
        "note du client", blank=True, validators=[MaxLengthValidator(CUSTOMER_NOTE_MAX_LENGTH)]
    )
    internal_note = models.TextField("note interne", blank=True)
    idempotency_key = models.CharField(
        "clé d'idempotence", max_length=64, unique=True, null=True, blank=True, editable=False
    )
    # Empreinte du contenu de la requête : même clé + autre contenu => refus (étape 13).
    idempotency_fingerprint = models.CharField(
        "empreinte de la requête", max_length=64, blank=True, editable=False
    )
    accepted_terms_at = models.DateTimeField("CGV acceptées le", null=True, blank=True)
    ready_at = models.DateTimeField("prête le", null=True, blank=True)
    collected_at = models.DateTimeField("retirée le", null=True, blank=True)
    cancelled_at = models.DateTimeField("annulée le", null=True, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="remise par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="annulée par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cancellation_reason = models.CharField("motif d'annulation", max_length=255, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "commande"
        verbose_name_plural = "commandes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="orders_status_created_idx"),
            models.Index(fields=["customer_phone"], name="orders_customer_phone_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=OrderStatus.values), name="orders_status_valid"),
            models.CheckConstraint(
                condition=Q(payment_status__in=PaymentStatus.values), name="orders_payment_status_valid"
            ),
            models.CheckConstraint(condition=Q(currency="XOF"), name="orders_currency_xof"),
            models.CheckConstraint(
                condition=Q(total_xof=F("subtotal_xof") - F("discount_xof") + F("shipping_fee_xof")),
                name="orders_total_consistent",
            ),
            models.CheckConstraint(
                condition=Q(discount_xof__lte=F("subtotal_xof")), name="orders_discount_le_subtotal"
            ),
            models.CheckConstraint(
                condition=~Q(fulfillment_method=FulfillmentMethod.CLICK_AND_COLLECT)
                | Q(pickup_point__isnull=False),
                name="orders_click_and_collect_has_pickup_point",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=[OrderStatus.READY_FOR_PICKUP, OrderStatus.COLLECTED])
                | Q(ready_at__isnull=False),
                name="orders_ready_has_date",
            ),
            models.CheckConstraint(
                condition=~Q(status=OrderStatus.COLLECTED) | Q(collected_at__isnull=False),
                name="orders_collected_has_date",
            ),
            models.CheckConstraint(
                condition=~Q(status=OrderStatus.CANCELLED)
                | (Q(cancelled_at__isnull=False) & ~Q(cancellation_reason="")),
                name="orders_cancelled_has_date_and_reason",
            ),
        ]

    def __str__(self):
        return self.public_reference

    def _normalize(self):
        self.customer_phone = _normalized_phone(self.customer_phone)
        self.customer_email = (self.customer_email or "").strip().lower()

    def clean_fields(self, exclude=None):
        self._normalize()
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self._normalize()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DeletionForbidden("Une commande ne peut pas être supprimée : annulez-la.")

    @property
    def masked_name(self) -> str:
        """« A. K. » : suivi public sans donnée personnelle."""
        initials = [part.strip()[:1].upper() for part in (self.customer_first_name, self.customer_last_name)]
        return " ".join(f"{initial}." for initial in initials if initial)

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    @property
    def payment_status_label(self) -> str:
        return self.get_payment_status_display()


class OrderItem(TimeStampedModel):
    """Ligne : instantané du produit (le nom peut changer ensuite) et attribution déduite du QR (R06, R09)."""

    order = models.ForeignKey(Order, verbose_name="commande", on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        ProductVariant, verbose_name="variante", on_delete=models.PROTECT, related_name="order_items"
    )
    product = models.ForeignKey(
        Product, verbose_name="produit", on_delete=models.PROTECT, related_name="order_items"
    )
    product_name = models.CharField("produit (à la commande)", max_length=160)
    product_reference = models.CharField("référence (à la commande)", max_length=40)
    variant_label = models.CharField("variante (à la commande)", max_length=120)
    sku = models.CharField("SKU (à la commande)", max_length=60)
    unit_price_xof = models.PositiveIntegerField("prix unitaire (XOF)", validators=[MinValueValidator(1)])
    quantity = models.PositiveSmallIntegerField("quantité", validators=[MinValueValidator(1)])
    line_total_xof = models.PositiveIntegerField("total de la ligne (XOF)")
    source_qr = models.ForeignKey(
        QRCode,
        verbose_name="QR source",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    source_box = models.ForeignKey(
        Box,
        verbose_name="box source",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    source_product = models.ForeignKey(
        Product,
        verbose_name="produit source",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "ligne de commande"
        verbose_name_plural = "lignes de commande"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="orders_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price_xof__gt=0), name="orders_item_price_positive"),
            models.CheckConstraint(
                condition=Q(line_total_xof=F("unit_price_xof") * F("quantity")),
                name="orders_item_line_total_consistent",
            ),
            # Attribution cohérente : QR, box et produit source renseignés ensemble, ou pas du tout…
            models.CheckConstraint(
                condition=(
                    Q(source_qr__isnull=True) & Q(source_box__isnull=True) & Q(source_product__isnull=True)
                )
                | (
                    Q(source_qr__isnull=False) & Q(source_box__isnull=False) & Q(source_product__isnull=False)
                ),
                name="orders_item_source_complete",
            ),
            # … et le produit source est forcément le produit de la ligne.
            models.CheckConstraint(
                condition=Q(source_product__isnull=True) | Q(source_product=F("product")),
                name="orders_item_source_product_matches",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.product_name} – {self.variant_label}"


class OrderStatusHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise DeletionForbidden("L'historique des statuts ne se modifie pas.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise DeletionForbidden("L'historique des statuts ne se modifie pas.")

    def delete(self):
        raise DeletionForbidden("L'historique des statuts ne se supprime pas.")


class OrderStatusHistory(TimeStampedModel):
    order = models.ForeignKey(
        Order, verbose_name="commande", on_delete=models.CASCADE, related_name="status_history"
    )
    # Vide à la création de la commande (une seule valeur « vide » : pas de null sur un champ texte).
    from_status = models.CharField("statut précédent", max_length=30, choices=OrderStatus.choices, blank=True)
    to_status = models.CharField("nouveau statut", max_length=30, choices=OrderStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Vide : client ou système.",
    )
    note = models.CharField("note", max_length=255, blank=True)

    objects = OrderStatusHistoryQuerySet.as_manager()

    class Meta:
        verbose_name = "changement de statut"
        verbose_name_plural = "historique des statuts"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.from_status or '—'} → {self.to_status}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DeletionForbidden("L'historique des statuts ne se modifie pas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DeletionForbidden("L'historique des statuts ne se supprime pas.")
