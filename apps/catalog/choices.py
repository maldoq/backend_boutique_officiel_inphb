from django.db import models


class Availability(models.TextChoices):
    """Disponibilité calculée d'une variante ou d'un produit (jamais stockée)."""

    IN_STOCK = "in_stock", "En stock"
    LOW_STOCK = "low_stock", "Stock limité"
    OUT_OF_STOCK = "out_of_stock", "Rupture"
    COMING_SOON = "coming_soon", "Bientôt disponible"


# Du plus favorable au moins favorable : la disponibilité d'un produit est la meilleure de ses variantes.
AVAILABILITY_RANK = {
    Availability.IN_STOCK: 0,
    Availability.LOW_STOCK: 1,
    Availability.OUT_OF_STOCK: 2,
}
