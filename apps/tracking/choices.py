from django.db import models


class EventType(models.TextChoices):
    """Étapes du tunnel BOX → SCAN → VISITE → PANIER → COMMANDE."""

    QR_SCAN = "qr_scan", "Scan de QR code"
    PRODUCT_VIEW = "product_view", "Consultation de produit"
    ADD_TO_CART = "add_to_cart", "Ajout au panier"
    REMOVE_FROM_CART = "remove_from_cart", "Retrait du panier"
    CHECKOUT_STARTED = "checkout_started", "Début de commande"
    ORDER_CREATED = "order_created", "Commande créée"


# Types émis uniquement par le serveur (un client ne peut pas les envoyer).
SERVER_ONLY_EVENTS = frozenset({EventType.QR_SCAN, EventType.ORDER_CREATED})
CLIENT_EVENTS = frozenset(set(EventType) - SERVER_ONLY_EVENTS)
# Produit obligatoire / variante obligatoire selon le type.
PRODUCT_REQUIRED = frozenset({EventType.PRODUCT_VIEW, EventType.ADD_TO_CART, EventType.REMOVE_FROM_CART})
VARIANT_REQUIRED = frozenset({EventType.ADD_TO_CART, EventType.REMOVE_FROM_CART})
# Comptés une seule fois par visiteur dans la fenêtre anti-doublon (rafraîchissement de page).
DEDUPLICATED_EVENTS = frozenset({EventType.PRODUCT_VIEW, EventType.CHECKOUT_STARTED})
