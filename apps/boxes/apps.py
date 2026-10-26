from django.apps import AppConfig


class BoxesConfig(AppConfig):
    name = "apps.boxes"
    label = "boxes"
    verbose_name = "Boxes et QR codes"

    def ready(self):
        from . import checks  # noqa: F401  (longueur des codes QR)
