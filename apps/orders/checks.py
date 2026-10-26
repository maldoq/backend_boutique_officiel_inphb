from django.conf import settings
from django.core.checks import Error, register

SUPPORTED_STOCK_POLICIES = ("reserve_on_order",)


@register()
def stock_policy_check(app_configs, **kwargs):
    """Seule la réservation du stock à la commande (décision D06) est implémentée."""
    if settings.STOCK_POLICY not in SUPPORTED_STOCK_POLICIES:
        return [
            Error(
                f"STOCK_POLICY vaut « {settings.STOCK_POLICY} ».",
                hint=f"Valeurs prises en charge : {', '.join(SUPPORTED_STOCK_POLICIES)} (décision D06).",
                id="orders.E001",
            )
        ]
    return []
