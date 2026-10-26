"""Lectures du stock : alertes (même règle que la disponibilité publique) et contrôle de cohérence."""

from django.db.models import F, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import ProductVariant
from apps.core.models import SiteSettings


def _alerts(default_threshold: int | None) -> QuerySet[ProductVariant]:
    """Variantes actives de produits actifs dont le stock est ≤ au seuil (variante, sinon boutique).

    Les produits « bientôt disponibles » sont inclus : product.is_coming_soon permet de les distinguer.
    """
    if default_threshold is None:
        default_threshold = SiteSettings.load().default_low_stock_threshold
    return (
        ProductVariant.objects.filter(is_active=True, product__is_active=True)
        .annotate(alert_threshold=Coalesce("low_stock_threshold", Value(default_threshold)))
        .filter(stock_quantity__lte=F("alert_threshold"))
        .select_related("product", "product__category")
        .order_by("stock_quantity", "product__name", "position", "id")
    )


def low_stock_variants(default_threshold: int | None = None) -> QuerySet[ProductVariant]:
    """Stock faible : 0 < stock ≤ seuil."""
    return _alerts(default_threshold).filter(stock_quantity__gt=0)


def out_of_stock_variants(default_threshold: int | None = None) -> QuerySet[ProductVariant]:
    """Rupture : stock = 0."""
    return _alerts(default_threshold).filter(stock_quantity=0)


def stock_drift() -> QuerySet[ProductVariant]:
    """Variantes dont le stock diffère de la somme de leurs mouvements (modification hors service)."""
    return (
        ProductVariant.objects.annotate(movements_total=Coalesce(Sum("stock_movements__delta"), 0))
        .exclude(movements_total=F("stock_quantity"))
        .select_related("product")
        .order_by("product__name", "id")
    )
