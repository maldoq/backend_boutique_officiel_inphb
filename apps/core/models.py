from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .phone import InvalidPhoneNumber, normalize_phone


class TimeStampedModel(models.Model):
    """Ajoute created_at (indexé) et updated_at à tous les modèles métier (D.4)."""

    created_at = models.DateTimeField("créé le", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        abstract = True


def default_low_stock_threshold() -> int:
    """Valeur initiale reprise de DEFAULT_LOW_STOCK_THRESHOLD (.env), ensuite modifiable dans l'admin."""
    return settings.DEFAULT_LOW_STOCK_THRESHOLD


class SiteSettings(TimeStampedModel):
    """Paramètres de la boutique modifiables depuis l'admin : une seule ligne (pk = 1)."""

    SINGLETON_PK = 1

    shop_name = models.CharField("nom de la boutique", max_length=120, default="Boutique INP-HB")
    slogan = models.CharField("slogan", max_length=120, default="FORMER – INNOVER – PRODUIRE")
    contact_phone = models.CharField("téléphone de contact", max_length=20, blank=True)
    contact_email = models.EmailField("e-mail de contact", blank=True)
    default_low_stock_threshold = models.PositiveSmallIntegerField(
        "seuil de stock faible par défaut", default=default_low_stock_threshold
    )
    pickup_hold_days = models.PositiveSmallIntegerField(
        "durée de conservation des commandes prêtes (jours)", default=7
    )
    order_confirmation_message = models.TextField("message après commande", blank=True)
    maintenance_mode = models.BooleanField(
        "mode maintenance",
        default=False,
        help_text="Si activé, la création de commande est refusée (503).",
    )

    class Meta:
        verbose_name = "paramètres de la boutique"
        verbose_name_plural = "paramètres de la boutique"

    def __str__(self):
        return self.shop_name

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        if self._state.adding:
            # Nouvelle instance alors que la ligne existe : on la met à jour en gardant sa date de création.
            created_at = type(self).objects.filter(pk=self.pk).values_list("created_at", flat=True).first()
            if created_at is not None:
                self.created_at = created_at
                self._state.adding = False
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Les paramètres de la boutique ne peuvent pas être supprimés.")

    def clean(self):
        super().clean()
        if self.contact_phone:
            try:
                self.contact_phone = normalize_phone(self.contact_phone)
            except InvalidPhoneNumber as exc:
                raise ValidationError({"contact_phone": str(exc)}) from exc

    @classmethod
    def load(cls) -> "SiteSettings":
        """Renvoie l'unique ligne de paramètres, créée avec les valeurs par défaut si besoin."""
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj
