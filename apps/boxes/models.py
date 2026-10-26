import re

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.catalog.models import Product
from apps.core.codes import ALPHABET
from apps.core.models import TimeStampedModel

BOX_CODE_VALIDATOR = RegexValidator(r"^BOX-[A-Z0-9]+(-[A-Z0-9]+)*$", "Format attendu : BOX-CENTRE-01.")
QR_CODE_MAX_LENGTH = 16
_QR_CODE = re.compile(rf"^[{ALPHABET}]{{4,{QR_CODE_MAX_LENGTH}}}$")


def normalize_box_code(value: str) -> str:
    """« box centre 01 » -> « BOX-CENTRE-01 »."""
    return "-".join((value or "").split()).upper()


def normalize_qr_code(value: str) -> str | None:
    """Code QR saisi ou lu : espaces retirés, majuscules ; None si le code est impossible."""
    code = "".join((value or "").split()).upper()
    return code if _QR_CODE.match(code) else None


class Box(TimeStampedModel):
    """Box vitrée physique installée sur un campus."""

    code = models.CharField(
        "code", max_length=40, unique=True, validators=[BOX_CODE_VALIDATOR], help_text="Ex. BOX-CENTRE-01"
    )
    label = models.CharField("libellé", max_length=120, help_text="Ex. Box Hall Centre")
    site = models.CharField("site", max_length=80, help_text="Campus ou site : Centre, ESA, ESTP…")
    location_details = models.CharField("emplacement précis", max_length=255, blank=True)
    is_active = models.BooleanField(
        "active", default=True, help_text="Inactive : ses QR codes ne s'ouvrent plus (410)."
    )
    notes = models.TextField("notes internes", blank=True)

    class Meta:
        verbose_name = "box vitrée"
        verbose_name_plural = "boxes vitrées"
        ordering = ["site", "code"]

    def __str__(self):
        return f"{self.code} — {self.label}"

    def clean_fields(self, exclude=None):
        self.code = normalize_box_code(self.code)  # avant la validation du format
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self.code = normalize_box_code(self.code)
        super().save(*args, **kwargs)


class QRCode(TimeStampedModel):
    """QR dynamique : le code imprimé ne change pas, sa destination (box, produit) peut être réaffectée."""

    code = models.CharField("code", max_length=QR_CODE_MAX_LENGTH, unique=True, editable=False)
    box = models.ForeignKey(Box, verbose_name="box", on_delete=models.PROTECT, related_name="qr_codes")
    product = models.ForeignKey(
        Product, verbose_name="produit", on_delete=models.PROTECT, related_name="qr_codes"
    )
    is_active = models.BooleanField("actif", default=True)
    activated_at = models.DateTimeField("activé le", null=True, blank=True, editable=False)
    deactivated_at = models.DateTimeField("désactivé le", null=True, blank=True, editable=False)
    replaced_by = models.ForeignKey(
        "self",
        verbose_name="remplacé par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replaces",
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    note = models.CharField("note", max_length=255, blank=True)

    class Meta:
        verbose_name = "QR code"
        verbose_name_plural = "QR codes"
        ordering = ["box__code", "product__name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["box", "product"],
                condition=Q(is_active=True),
                name="boxes_one_active_qr_per_box_product",
                violation_error_message="Un QR actif existe déjà pour ce produit dans cette box.",
            ),
        ]
        indexes = [models.Index(fields=["box", "is_active"], name="boxes_qr_box_active_idx")]

    def __str__(self):
        return f"{self.code} ({self.box.code} – {self.product.name})"

    @property
    def public_url(self) -> str:
        """URL encodée dans le QR imprimé (le site Angular et l'app Flutter l'interceptent)."""
        return f"{settings.PUBLIC_WEB_BASE_URL}/q/{self.code}"
