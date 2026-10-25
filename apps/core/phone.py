"""Normalisation des numéros de téléphone au format international E.164 (+225…)."""

import re

from django.core.exceptions import ValidationError

_SEPARATORS = re.compile(r"[\s.\-()/]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
CI_PREFIX = "+225"
CI_NATIONAL_LENGTH = 10  # plan de numérotation ivoirien à 10 chiffres (depuis 2021)
CI_INTERNATIONAL_DIGITS = 3 + CI_NATIONAL_LENGTH  # 225 + 10 chiffres


class InvalidPhoneNumber(ValueError):
    """Numéro impossible à normaliser."""


def normalize_phone(raw: str) -> str:
    """Normalise un numéro ivoirien ou international en E.164 ; lève InvalidPhoneNumber sinon."""
    if raw is None:
        raise InvalidPhoneNumber("Numéro de téléphone manquant.")
    value = _SEPARATORS.sub("", str(raw))
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.isdigit() and len(value) == CI_NATIONAL_LENGTH and value.startswith("0"):
        value = CI_PREFIX + value  # 07 00 00 00 00 -> +2250700000000
    elif value.isdigit() and len(value) == CI_INTERNATIONAL_DIGITS and value.startswith("225"):
        value = "+" + value  # 2250700000000 -> +2250700000000
    if not _E164.match(value):
        raise InvalidPhoneNumber("Numéro de téléphone invalide.")
    if value.startswith(CI_PREFIX) and len(value) != 1 + CI_INTERNATIONAL_DIGITS:
        raise InvalidPhoneNumber("Un numéro ivoirien comporte 10 chiffres après +225.")
    return value


def validate_phone(value: str) -> None:
    """Validateur Django (modèles, formulaires) : refuse un numéro non normalisable."""
    try:
        normalize_phone(value)
    except InvalidPhoneNumber as exc:
        raise ValidationError(str(exc), code="invalid_phone") from exc
