from django.conf import settings
from django.core.checks import Error, register

from .models import QR_CODE_MAX_LENGTH


@register()
def qr_code_length_check(app_configs, **kwargs):
    if not 8 <= settings.QR_CODE_LENGTH <= QR_CODE_MAX_LENGTH:
        return [
            Error(
                f"QR_CODE_LENGTH vaut {settings.QR_CODE_LENGTH}.",
                hint=f"Entre 8 (codes non devinables) et {QR_CODE_MAX_LENGTH} (taille du champ en base).",
                id="boxes.E001",
            )
        ]
    return []
