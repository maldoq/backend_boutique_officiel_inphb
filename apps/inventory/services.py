"""Seul point de modification du stock (R04) : verrouillé, historisé, jamais négatif.

Sûreté en concurrence : le stock est modifié par UNE requête SQL conditionnelle
(« ajouter delta seulement si le résultat reste ≥ 0 »). Elle est atomique même sans verrou
de ligne, donc correcte sous SQLite (qui ignore SELECT … FOR UPDATE) comme sous PostgreSQL.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import log_action
from apps.catalog.models import ProductVariant
from apps.core.exceptions import BusinessError, ConflictError, InsufficientStock, NotFoundError

from .choices import DECREASE_ONLY, INCREASE_ONLY, MANUAL_REASONS, NOTE_REQUIRED, StockReason
from .models import StockMovement

MAX_STOCK = 1_000_000
NOTE_MAX_LENGTH = 255


class StockLimitExceeded(BusinessError):
    status_code, code = 400, "stock_limit_exceeded"


def _direction_error(reason: str, delta: int) -> str | None:
    if reason in INCREASE_ONLY and delta < 0:
        return f"Le motif « {StockReason(reason).label} » ne peut qu'augmenter le stock."
    if reason in DECREASE_ONLY and delta > 0:
        return f"Le motif « {StockReason(reason).label} » ne peut que diminuer le stock."
    return None


def apply_movement(
    *, variant: ProductVariant, delta: int, reason: str, user=None, order=None, note: str = ""
) -> StockMovement:
    """Applique delta au stock de la variante et l'historise ; refuse tout stock final négatif.

    `order` : commande à l'origine du mouvement (réservation, annulation), sans import de `orders`.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("apply_movement doit être appelé dans une transaction (transaction.atomic).")
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        raise ValueError("delta doit être un entier non nul.")
    if reason not in StockReason.values:
        raise ValueError(f"Motif de mouvement inconnu : {reason!r}")
    if message := _direction_error(reason, delta):
        raise ValueError(message)

    updated = ProductVariant.objects.filter(
        pk=variant.pk,
        stock_quantity__gte=max(0, -delta),  # stock + delta >= 0
        stock_quantity__lte=MAX_STOCK - max(0, delta),  # stock + delta <= MAX_STOCK
    ).update(stock_quantity=F("stock_quantity") + delta, updated_at=timezone.now())

    current = ProductVariant.objects.filter(pk=variant.pk).values_list("stock_quantity", flat=True).first()
    if current is None:
        raise NotFoundError("Variante introuvable.")
    if not updated:
        if delta < 0:
            raise InsufficientStock(
                f"Stock insuffisant pour « {variant.product.name} – {variant.label} ».",
                details={"items": [{"variant_id": variant.pk, "requested": -delta, "available": current}]},
            )
        raise StockLimitExceeded(f"Le stock ne peut pas dépasser {MAX_STOCK} unités.")

    variant.stock_quantity = current
    return StockMovement.objects.create(
        variant=variant,
        delta=delta,
        reason=reason,
        balance_after=current,
        order=order,
        created_by=user,
        note=(note or "")[:NOTE_MAX_LENGTH],
    )


def _validated_note(reason: str, note: str) -> str:
    note = (note or "").strip()
    if reason in NOTE_REQUIRED and not note:
        raise ValidationError({"note": ["Une note est obligatoire pour ce motif (cause de l'écart)."]})
    if len(note) > NOTE_MAX_LENGTH:
        raise ValidationError({"note": [f"{NOTE_MAX_LENGTH} caractères au maximum."]})
    return note


def _validated_amounts(new_quantity, delta) -> None:
    if (new_quantity is None) == (delta is None):
        raise ValidationError(
            {"non_field_errors": ["Indiquez soit la nouvelle quantité, soit la variation."]}
        )
    if new_quantity is not None and not (0 <= new_quantity <= MAX_STOCK):
        raise ValidationError({"new_quantity": [f"Entre 0 et {MAX_STOCK}."]})
    if delta is not None and (delta == 0 or abs(delta) > MAX_STOCK):
        raise ValidationError({"delta": [f"Variation non nulle, au plus {MAX_STOCK} en valeur absolue."]})


def adjust_stock(
    *,
    variant_id: int,
    user,
    reason: str,
    new_quantity: int | None = None,
    delta: int | None = None,
    note: str = "",
    request=None,
) -> StockMovement:
    """Ajustement manuel par le personnel (nouvelle quantité OU variation), audité (stock.adjust)."""
    if reason not in MANUAL_REASONS:
        raise ValidationError({"reason": ["Motif non autorisé pour un ajustement manuel."]})
    note = _validated_note(reason, note)
    _validated_amounts(new_quantity, delta)

    with transaction.atomic():
        variant = (
            ProductVariant.objects.select_for_update(of=("self",))
            .select_related("product")
            .filter(pk=variant_id)
            .first()
        )
        if variant is None:
            raise NotFoundError("Variante introuvable.")
        before = variant.stock_quantity
        if new_quantity is not None:
            delta = new_quantity - before
            if delta == 0:
                raise ValidationError({"new_quantity": [f"Le stock est déjà de {before}."]})
        if message := _direction_error(reason, delta):
            raise ValidationError({"reason": [message]})
        movement = apply_movement(variant=variant, delta=delta, reason=reason, user=user, note=note)
        log_action(
            actor=user,
            action="stock.adjust",
            obj=variant,
            changes={
                "stock_quantity": [before, movement.balance_after],
                "reason": [None, reason],
                "note": [None, note],
            },
            request=request,
        )
    return movement


def set_initial_stock(
    *, variant: ProductVariant, quantity: int, user=None, request=None
) -> StockMovement | None:
    """Premier stock d'une variante (motif « initial ») ; refusé si elle a déjà un historique."""
    if quantity < 0 or quantity > MAX_STOCK:
        raise ValidationError({"initial_stock": [f"Entre 0 et {MAX_STOCK}."]})
    if quantity == 0:
        return None
    with transaction.atomic():
        if variant.stock_quantity or StockMovement.objects.filter(variant_id=variant.pk).exists():
            raise ConflictError(
                "Cette variante a déjà du stock : utilisez un ajustement.", code="stock_already_initialized"
            )
        movement = apply_movement(variant=variant, delta=quantity, reason=StockReason.INITIAL, user=user)
        if user is not None:
            log_action(
                actor=user,
                action="stock.initial",
                obj=variant,
                changes={"stock_quantity": [0, quantity]},
                request=request,
            )
    return movement
