from django.db import models


class StockReason(models.TextChoices):
    INITIAL = "initial", "Stock initial"
    RESTOCK = "restock", "Réassort"
    MANUAL_ADJUSTMENT = "manual_adjustment", "Ajustement manuel"
    INVENTORY_CORRECTION = "inventory_correction", "Correction d'inventaire"
    ORDER_RESERVED = "order_reserved", "Réservation (commande)"
    ORDER_CANCELLED = "order_cancelled", "Remise en stock (annulation)"
    RETURN = "return", "Retour"


# Motifs utilisables par le personnel ; les autres sont réservés au système (création, commandes).
MANUAL_REASONS = frozenset(
    {StockReason.RESTOCK, StockReason.MANUAL_ADJUSTMENT, StockReason.INVENTORY_CORRECTION, StockReason.RETURN}
)
# Sens imposé par le motif.
INCREASE_ONLY = frozenset(
    {StockReason.INITIAL, StockReason.RESTOCK, StockReason.ORDER_CANCELLED, StockReason.RETURN}
)
DECREASE_ONLY = frozenset({StockReason.ORDER_RESERVED})
# Motifs dont l'explication est obligatoire (casse, vol, erreur d'inventaire…).
NOTE_REQUIRED = frozenset({StockReason.MANUAL_ADJUSTMENT, StockReason.INVENTORY_CORRECTION})
