from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = "apps.orders"
    label = "orders"
    verbose_name = "Commandes"

    def ready(self):
        from apps.core.app_config import register_app_config_section

        from . import checks  # noqa: F401  (politique de stock prise en charge)
        from .selectors import pickup_points_for_app_config

        register_app_config_section("pickup_points", pickup_points_for_app_config)
