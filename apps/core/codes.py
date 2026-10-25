"""Codes publics opaques et non devinables (R12) : références de commande, codes de retrait, codes QR."""

import secrets

from django.db import models

# Sans caractères ambigus à la lecture ou à la saisie : ni 0/O, ni 1/I.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class CodeGenerationError(RuntimeError):
    """Aucun code libre trouvé après plusieurs essais (alphabet ou longueur trop petits)."""


def random_code(length: int, alphabet: str = ALPHABET) -> str:
    """Code aléatoire cryptographiquement sûr (module secrets)."""
    if length < 1:
        raise ValueError("La longueur du code doit être au moins 1.")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def unique_code(
    model: type[models.Model], field: str, length: int, *, prefix: str = "", attempts: int = 10
) -> str:
    """Code aléatoire absent de model.field ; la contrainte unique en base reste la garantie finale."""
    manager = model._default_manager
    for _ in range(attempts):
        code = f"{prefix}{random_code(length)}"
        if not manager.filter(**{field: code}).exists():
            return code
    raise CodeGenerationError(f"Impossible de générer un code unique pour {model.__name__}.{field}.")
