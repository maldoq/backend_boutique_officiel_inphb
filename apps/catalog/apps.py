from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalogue"

    def ready(self):
        from . import receivers  # noqa: F401  (fichiers d'images, image principale, produits associés)
