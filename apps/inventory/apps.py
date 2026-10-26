from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Stocks"

    def ready(self):
        from . import receivers  # noqa: F401  (stock initial des variantes créées par le catalogue)
