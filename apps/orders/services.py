"""Panier et commandes invitées : prix et totaux serveur (R01), jamais « payée » (R02), stock jamais
négatif et décrémenté dans la même transaction (R04), attribution prouvée par ligne (R06, R09).
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import ProductVariant
from apps.catalog.selectors import visible_products
from apps.core.codes import unique_code
from apps.core.exceptions import (
    BusinessError,
    ConflictError,
    InsufficientStock,
    NotFoundError,
    ServiceUnavailableError,
)
from apps.core.models import SiteSettings
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.inventory.choices import StockReason
from apps.inventory.services import apply_movement
from apps.tracking.services import find_attribution, record_order_created

from .choices import FulfillmentMethod, OrderStatus, PaymentStatus
from .models import Order, OrderItem, OrderStatusHistory, PickupPoint
from .signals import order_created

PAYMENT_DISABLED_MESSAGE = (
    "Le paiement en ligne n’est pas encore activé. "
    "Votre commande est enregistrée et en attente de validation par la Boutique."
)
REFERENCE_PREFIX = "CMD-"


class QuantityLimitExceeded(BusinessError):
    status_code, code = 400, "quantity_limit_exceeded"


class PickupPointUnavailable(BusinessError):
    status_code, code = 400, "pickup_point_unavailable"


class ProductUnavailable(ConflictError):
    code = "product_unavailable"


class IdempotencyConflict(ConflictError):
    code = "idempotency_conflict"


# --- Lignes du panier -----------------------------------------------------------------------


@dataclass
class CartLine:
    variant_id: int
    quantity: int
    source_qr_code: str | None = None
    expected_unit_price_xof: int | None = None


def merge_lines(items) -> list[CartLine]:
    """Fusionne les lignes identiques (même variante ET même QR source), dans l'ordre d'arrivée."""
    merged: dict[tuple, CartLine] = {}
    for item in items:
        code = "".join(str(item.get("source_qr_code") or "").split()).upper() or None
        key = (item["variant_id"], code)
        if key in merged:
            merged[key].quantity += item["quantity"]
        else:
            merged[key] = CartLine(
                item["variant_id"], item["quantity"], code, item.get("expected_unit_price_xof")
            )
    return list(merged.values())


def quantities_by_variant(lines: list[CartLine]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for line in lines:
        totals[line.variant_id] += line.quantity
    return dict(totals)


def _variants(ids, *, lock: bool = False) -> dict[int, ProductVariant]:
    queryset = ProductVariant.objects.select_related("product").filter(id__in=ids).order_by("id")
    if lock:
        # Ordre déterministe (évite les interblocages) ; SQLite ignore le verrou, la décrémentation
        # conditionnelle d'apply_movement reste la garantie (étape 7).
        queryset = queryset.select_for_update(of=("self",))
    return {variant.pk: variant for variant in queryset}


def _orderable_ids(variants) -> set[int]:
    """Variantes commandables : actives, produit visible au public et pas « bientôt disponible »."""
    visible = set(
        visible_products().filter(pk__in={v.product_id for v in variants}).values_list("pk", flat=True)
    )
    return {
        v.pk for v in variants if v.is_active and v.product_id in visible and not v.product.is_coming_soon
    }


def _item(variant: ProductVariant) -> dict:
    return {"variant_id": variant.pk, "product_name": variant.product.name, "variant_label": variant.label}


# --- Validation du panier (aucune écriture) ------------------------------------------------------


def validate_cart(*, items, visitor_id: UUID | None) -> dict:
    """Prix, disponibilités et totaux serveur du panier, avec les problèmes ligne par ligne."""
    lines = merge_lines(items)
    variants = _variants({line.variant_id for line in lines})
    orderable = _orderable_ids(variants.values())
    totals = quantities_by_variant(lines)
    default_threshold = SiteSettings.load().default_low_stock_threshold
    max_qty = settings.MAX_QTY_PER_LINE
    rows, subtotal, blocking = [], 0, False
    for line in lines:
        variant = variants.get(line.variant_id)
        issues = []
        if variant is None:
            rows.append(
                {
                    "variant_id": line.variant_id,
                    "product_name": None,
                    "variant_label": None,
                    "unit_price_xof": None,
                    "quantity": line.quantity,
                    "line_total_xof": 0,
                    "availability": None,
                    "max_orderable_quantity": 0,
                    "attribution_applied": False,
                    "issues": [{"code": "product_unavailable", "message": "Cet article n'existe plus."}],
                }
            )
            blocking = True
            continue
        variant.prime_default_threshold(default_threshold)
        unit = variant.effective_price_xof
        available = variant.stock_quantity if variant.pk in orderable else 0
        requested = totals[variant.pk]
        if variant.pk not in orderable:
            issues.append(
                {"code": "product_unavailable", "message": "Cet article n'est pas disponible à la vente."}
            )
        elif available == 0:
            issues.append({"code": "out_of_stock", "message": "Cette variante est en rupture."})
        elif requested > available:
            issues.append(
                {"code": "insufficient_stock", "message": f"Stock insuffisant : {available} disponible(s)."}
            )
        if requested > max_qty:
            issues.append(
                {"code": "quantity_limit_exceeded", "message": f"{max_qty} unités au maximum par article."}
            )
        blocking = blocking or bool(issues)
        if line.expected_unit_price_xof is not None and line.expected_unit_price_xof != unit:
            issues.append({"code": "price_changed", "message": f"Le prix est désormais de {unit} XOF."})
        attribution = (
            find_attribution(
                source_qr_code=line.source_qr_code, product=variant.product, visitor_id=visitor_id
            )
            if visitor_id
            else None
        )
        rows.append(
            {
                "variant_id": variant.pk,
                "product_name": variant.product.name,
                "variant_label": variant.label,
                "unit_price_xof": unit,
                "quantity": line.quantity,
                "line_total_xof": unit * line.quantity,
                "availability": variant.availability,
                "max_orderable_quantity": min(available, max_qty),
                "attribution_applied": attribution is not None,
                "issues": issues,
            }
        )
        subtotal += unit * line.quantity
    maintenance = SiteSettings.load().maintenance_mode
    return {
        "items": rows,
        "subtotal_xof": subtotal,
        "discount_xof": 0,
        "fees_xof": 0,
        "total_xof": subtotal,
        "currency": "XOF",
        "is_valid": bool(rows) and not blocking and not maintenance,
        "maintenance_mode": maintenance,
    }


# --- Création de commande ----------------------------------------------------------------------


@dataclass
class OrderResult:
    order: Order
    created: bool
    warnings: list = field(default_factory=list)


def payload_fingerprint(payload: dict) -> str:
    """Empreinte stable du contenu de la requête (idempotence : même clé => même contenu exigé)."""
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay(order: Order, fingerprint: str) -> OrderResult:
    if order.idempotency_fingerprint != fingerprint:
        raise IdempotencyConflict(
            "Cette clé d'idempotence a déjà servi pour une autre commande.", details={"idempotency_key": True}
        )
    return OrderResult(order=order, created=False)


def find_by_idempotency_key(key: str | None) -> Order | None:
    return Order.objects.filter(idempotency_key=key).first() if key else None


def _active_pickup_point(pickup_point_id) -> PickupPoint:
    point = PickupPoint.objects.filter(pk=pickup_point_id, is_active=True).first()
    if point is None:
        raise PickupPointUnavailable(
            "Ce point de retrait est inconnu ou inactif.", details={"pickup_point_id": pickup_point_id}
        )
    return point


def _check_orderable(lines, variants) -> None:
    unknown = [line.variant_id for line in lines if line.variant_id not in variants]
    if unknown:
        raise NotFoundError(
            "Un ou plusieurs articles n'existent plus.",
            details={"items": [{"variant_id": pk} for pk in unknown]},
        )
    orderable = _orderable_ids(variants.values())
    unavailable = [_item(variants[pk]) for pk in sorted({line.variant_id for line in lines} - orderable)]
    if unavailable:
        raise ProductUnavailable(
            "Un ou plusieurs articles ne sont pas disponibles à la vente.", details={"items": unavailable}
        )
    over = [
        {**_item(variants[pk]), "requested": qty, "max": settings.MAX_QTY_PER_LINE}
        for pk, qty in quantities_by_variant(lines).items()
        if qty > settings.MAX_QTY_PER_LINE
    ]
    if over:  # limite sur le TOTAL par variante : de faux QR ne permettent pas de la contourner
        raise QuantityLimitExceeded(
            f"{settings.MAX_QTY_PER_LINE} unités au maximum par article.", details={"items": over}
        )


def _check_stock(lines, variants) -> None:
    """Toutes les variantes en défaut d'un coup (la décrémentation reste conditionnelle ensuite)."""
    deficits = [
        {**_item(variants[pk]), "requested": qty, "available": variants[pk].stock_quantity}
        for pk, qty in quantities_by_variant(lines).items()
        if qty > variants[pk].stock_quantity
    ]
    if deficits:
        first = deficits[0]
        raise InsufficientStock(
            f"Stock insuffisant pour « {first['product_name']} – {first['variant_label']} ».",
            details={
                "items": [
                    {key: row[key] for key in ("variant_id", "requested", "available")} for row in deficits
                ]
            },
        )


def _create(*, payload, channel, visitor_id, idempotency_key, fingerprint) -> OrderResult:
    with transaction.atomic():
        pickup_point = _active_pickup_point(payload["pickup_point_id"])
        lines = merge_lines(payload["items"])
        if len(lines) > settings.MAX_LINES_PER_ORDER:
            raise QuantityLimitExceeded(f"{settings.MAX_LINES_PER_ORDER} lignes au maximum par commande.")
        variants = _variants({line.variant_id for line in lines}, lock=True)
        _check_orderable(lines, variants)
        _check_stock(lines, variants)

        customer = payload["customer"]
        order = Order.objects.create(
            public_reference=unique_code(Order, "public_reference", 8, prefix=REFERENCE_PREFIX),
            pickup_code=unique_code(Order, "pickup_code", 6),
            status=OrderStatus.PENDING,
            payment_status=PaymentStatus.UNPAID,  # jamais « payée » sans confirmation vérifiée (R02)
            fulfillment_method=FulfillmentMethod.CLICK_AND_COLLECT,
            pickup_point=pickup_point,
            customer_first_name=customer["first_name"],
            customer_last_name=customer["last_name"],
            customer_phone=customer["phone"],
            customer_email=customer.get("email", ""),
            customer_note=payload.get("customer_note", ""),
            # Date fixée ici (et non dans le contenu de la requête) : l'empreinte d'idempotence reste stable.
            accepted_terms_at=timezone.now() if payload.get("accept_terms") else None,
            channel=channel,
            visitor_id=visitor_id,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else "",
            currency="XOF",
        )
        warnings, subtotal, first_attribution = [], 0, None
        for line in lines:
            variant = variants[line.variant_id]
            attribution = (
                find_attribution(
                    source_qr_code=line.source_qr_code, product=variant.product, visitor_id=visitor_id
                )
                if line.source_qr_code and visitor_id
                else None
            )
            if line.source_qr_code and attribution is None:
                warnings.append(
                    {
                        "code": "attribution_ignored",
                        "source_qr_code": line.source_qr_code,
                        "variant_id": variant.pk,
                    }
                )
            unit = variant.effective_price_xof  # prix serveur (R01) : tout prix envoyé est ignoré
            OrderItem.objects.create(
                order=order,
                variant=variant,
                product=variant.product,
                product_name=variant.product.name,
                product_reference=variant.product.reference,
                variant_label=variant.label,
                sku=variant.sku,
                unit_price_xof=unit,
                quantity=line.quantity,
                line_total_xof=unit * line.quantity,
                source_qr=attribution.qr if attribution else None,
                source_box=attribution.box if attribution else None,
                source_product=variant.product if attribution else None,
            )
            subtotal += unit * line.quantity
            first_attribution = first_attribution or attribution

        for variant_id, quantity in quantities_by_variant(lines).items():  # R04 : même transaction
            apply_movement(
                variant=variants[variant_id], delta=-quantity, reason=StockReason.ORDER_RESERVED, order=order
            )

        order.subtotal_xof = order.total_xof = subtotal  # remises et frais : Phase 2
        order.source_qr = first_attribution.qr if first_attribution else None
        order.source_box = first_attribution.box if first_attribution else None
        order.save(update_fields=["subtotal_xof", "total_xof", "source_qr", "source_box", "updated_at"])
        OrderStatusHistory.objects.create(order=order, from_status="", to_status=order.status)
        record_order_created(order)
        transaction.on_commit(lambda: order_created.send(sender=Order, order=order))
    return OrderResult(order=order, created=True, warnings=warnings)


def create_order(
    *, payload: dict, channel: str, visitor_id: UUID | None, idempotency_key: str | None = None
) -> OrderResult:
    """Commande invitée Click & Collect, atomique et idempotente."""
    fingerprint = payload_fingerprint(payload)
    existing = find_by_idempotency_key(idempotency_key)
    if existing is not None:  # ré-essai réseau : même commande, stock décrémenté une seule fois
        return _replay(existing, fingerprint)
    if SiteSettings.load().maintenance_mode:
        raise ServiceUnavailableError(
            "Les commandes sont temporairement suspendues.", code="maintenance_mode"
        )
    try:
        return _create(
            payload=payload,
            channel=channel,
            visitor_id=visitor_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
    except IntegrityError:
        # Deux envois simultanés avec la même clé : la transaction perdante est annulée (stock compris),
        # puis on renvoie la commande créée par la gagnante.
        existing = find_by_idempotency_key(idempotency_key)
        if existing is None:
            raise
        return _replay(existing, fingerprint)


# --- Suivi --------------------------------------------------------------------------------------


def normalize_reference(value: str) -> str:
    return "".join(str(value or "").split()).upper()[:16]


def lookup_order(*, public_reference: str, phone: str) -> Order | None:
    """Commande si la référence ET le téléphone correspondent ; None sinon (sans dire lequel)."""
    try:
        normalized_phone = normalize_phone(phone)
    except InvalidPhoneNumber:
        return None
    return Order.objects.filter(
        public_reference=normalize_reference(public_reference), customer_phone=normalized_phone
    ).first()
