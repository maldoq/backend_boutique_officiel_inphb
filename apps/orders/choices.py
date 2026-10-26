from django.db import models


class OrderStatus(models.TextChoices):
    """Statut de traitement de la commande (indépendant du paiement, R03)."""

    PENDING = "pending", "En attente de validation"
    PREPARING = "preparing", "En préparation"
    READY_FOR_PICKUP = "ready_for_pickup", "Prête au retrait"
    COLLECTED = "collected", "Retirée"
    CANCELLED = "cancelled", "Annulée"


class PaymentStatus(models.TextChoices):
    """Statut du paiement : « paid » uniquement après une confirmation vérifiée de l'opérateur (R02)."""

    UNPAID = "unpaid", "Non payée"
    PENDING = "pending", "Paiement en cours"
    PAID = "paid", "Payée"
    FAILED = "failed", "Paiement échoué"
    REFUNDED = "refunded", "Remboursée"


class FulfillmentMethod(models.TextChoices):
    CLICK_AND_COLLECT = "click_and_collect", "Retrait en boutique"
