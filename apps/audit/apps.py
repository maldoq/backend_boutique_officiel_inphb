from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    label = "audit"
    verbose_name = "Journal d'audit"

    def ready(self):
        from . import receivers  # noqa: F401  (abonnement au signal core.sensitive_change)
