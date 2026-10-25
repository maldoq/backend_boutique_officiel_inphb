from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Comptes et rôles"

    def ready(self):
        from . import schema  # noqa: F401  (enregistre l'extension OpenAPI du JWT)
