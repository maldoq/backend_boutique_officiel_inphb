"""Écriture du journal d'audit (R14) : qui, quoi, sur quel objet, avant/après, depuis quelle IP.

À appeler DANS la transaction de l'opération auditée : si elle est annulée, la trace l'est aussi.
"""

import datetime
import decimal
import enum
import re
import uuid
from collections.abc import Iterable, Mapping

from django.db import models
from django.db.models.fields.files import FieldFile

from apps.core.request_context import get_client_ip

from .models import ACTION_REGEX, AuditLog

MASKED = "***"
REPR_LENGTH = 100
_ACTION = re.compile(ACTION_REGEX)
# Valeurs jamais écrites dans le journal (hachages, jetons, clés) : seule la modification est tracée.
_SENSITIVE_MARKERS = ("password", "secret", "token", "api_key", "apikey", "signature")


def is_sensitive_field(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def to_audit_value(value):
    """Convertit une valeur en JSON lisible et stable (objets liés : {id, repr})."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, enum.Enum):
        return to_audit_value(value.value)
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime.date | datetime.time):  # datetime hérite de date
        return value.isoformat()
    if isinstance(value, models.Model):
        return {"id": to_audit_value(value.pk), "repr": str(value)[:REPR_LENGTH]}
    if isinstance(value, FieldFile):
        return value.name or None
    if isinstance(value, Mapping):
        return {str(key): to_audit_value(item) for key, item in value.items()}
    if isinstance(value, models.Manager):
        value = value.all()
    if isinstance(value, set | frozenset):
        return sorted((to_audit_value(item) for item in value), key=str)
    if isinstance(value, Iterable) and not isinstance(value, bytes):
        return [to_audit_value(item) for item in value]
    return str(value)


def normalize_changes(changes: Mapping | None) -> dict:
    """{champ: [avant, après]} converti en JSON, valeurs sensibles masquées."""
    normalized = {}
    for field, pair in (changes or {}).items():
        values = pair if isinstance(pair, list | tuple) else [pair]
        # Un indicateur oui/non (ex. must_change_password) n'est jamais un secret.
        if is_sensitive_field(str(field)) and not all(isinstance(v, bool) or v is None for v in values):
            normalized[str(field)] = [MASKED, MASKED]
            continue
        if isinstance(pair, list | tuple) and len(pair) == 2:
            normalized[str(field)] = [to_audit_value(pair[0]), to_audit_value(pair[1])]
        else:
            normalized[str(field)] = to_audit_value(pair)
    return normalized


def diff_instance(
    instance: models.Model, validated_data: Mapping, fields: Iterable[str] | None = None
) -> dict:
    """Champs réellement modifiés : {champ: [avant, après]}. À appeler AVANT d'appliquer les données."""
    names = list(fields) if fields is not None else list(validated_data)
    changes = {}
    for name in names:
        if name not in validated_data:
            continue
        before = getattr(instance, name, None)
        after = validated_data[name]
        if to_audit_value(before) != to_audit_value(after):
            changes[name] = [before, after]
    return normalize_changes(changes)


def object_type_of(obj: models.Model) -> str:
    return f"{obj._meta.app_label}.{obj._meta.object_name}"


def log_action(*, actor, action: str, obj: models.Model, changes=None, request=None) -> AuditLog:
    """Écrit une entrée du journal d'audit (seul point d'écriture autorisé)."""
    if not _ACTION.match(action or ""):
        raise ValueError(f"Action d'audit invalide : {action!r} (format « domaine.verbe »).")
    if obj is None or obj.pk is None:
        raise ValueError("L'objet audité doit être enregistré (clé primaire requise).")
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None  # utilisateur anonyme : action du système ou d'un client
    is_staff_action = bool(actor and actor.is_staff)
    return AuditLog.objects.create(
        actor=actor,
        actor_email=actor.email if actor else "",
        action=action,
        object_type=object_type_of(obj),
        object_id=str(obj.pk),
        object_repr=str(obj)[:REPR_LENGTH],
        changes=normalize_changes(changes),
        ip_address=get_client_ip(request) if (request is not None and is_staff_action) else None,
    )
