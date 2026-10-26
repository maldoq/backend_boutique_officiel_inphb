from django.dispatch import receiver

from apps.catalog.signals import initial_stock_requested

from .services import set_initial_stock


@receiver(initial_stock_requested, dispatch_uid="inventory.initial_stock")
def create_initial_stock(sender, *, variant, quantity, user, request, **kwargs):
    """Stock initial d'une variante créée par le catalogue (même transaction : tout ou rien)."""
    set_initial_stock(variant=variant, quantity=quantity, user=user, request=request)
