"""Boxes vitrées et QR codes dynamiques : écritures validées, verrouillées et auditées (R14)."""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import diff_instance, log_action
from apps.catalog.models import Product
from apps.catalog.selectors import visible_products
from apps.core.codes import unique_code
from apps.core.exceptions import ConflictError

from .models import Box, QRCode

BOX_FIELDS = ("code", "label", "site", "location_details", "is_active", "notes")


class QrConflict(ConflictError):
    code = "qr_conflict"


def _validated(instance, *, exclude=None) -> None:
    try:
        instance.full_clean(exclude=exclude)
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages) from exc


# --- Boxes ----------------------------------------------------------------------------


@transaction.atomic
def create_box(*, data: dict, user, request=None, instance: Box | None = None) -> Box:
    box = instance or Box()
    for name in BOX_FIELDS:
        if name in data:
            setattr(box, name, data[name])
    _validated(box)
    box.save()
    log_action(
        actor=user,
        action="box.create",
        obj=box,
        changes={name: [None, getattr(box, name)] for name in ("code", "label", "site", "is_active")},
        request=request,
    )
    return box


@transaction.atomic
def update_box(*, box: Box, data: dict, user, request=None) -> Box:
    """Désactiver une box coupe la résolution de ses QR sans les modifier (réactivable)."""
    changes = diff_instance(box, data, BOX_FIELDS)
    for name in BOX_FIELDS:
        if name in data:
            setattr(box, name, data[name])
    _validated(box)
    box.save()
    if changes:
        action = "box.update"
        if list(changes) == ["is_active"]:
            action = "box.activate" if box.is_active else "box.deactivate"
        log_action(actor=user, action=action, obj=box, changes=changes, request=request)
    return box


def set_box_active(*, box: Box, active: bool, user, request=None) -> Box:
    return update_box(box=box, data={"is_active": active}, user=user, request=request)


# --- QR codes ------------------------------------------------------------------------


def _check_destination(box: Box, product: Product) -> None:
    """Pas de QR « mort » : la box et le produit doivent être actifs et le produit visible au public."""
    errors = {}
    if not box.is_active:
        errors["box_id"] = ["Cette box est inactive."]
    if not visible_products().filter(pk=product.pk).exists():
        errors["product_id"] = ["Ce produit n'est pas visible au public (inactif ou catégorie masquée)."]
    if errors:
        raise ValidationError(errors)


def _check_free(box: Box, product: Product, *, exclude: QRCode | None = None) -> None:
    others = QRCode.objects.filter(box=box, product=product, is_active=True)
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    if others.exists():
        raise QrConflict(
            "Un QR actif existe déjà pour ce produit dans cette box.",
            details={"qr_code": others.values_list("code", flat=True).first()},
        )


def check_assignment(
    box: Box, product: Product, *, exclude: QRCode | None = None, active: bool = True
) -> None:
    """Vérification préalable d'une destination (formulaires) : mêmes règles que les services."""
    if active:
        _check_destination(box, product)
        _check_free(box, product, exclude=exclude)


def _save_unique(qr: QRCode) -> None:
    """Enregistre en traduisant une collision concurrente sur « un QR actif par couple » en 409."""
    try:
        with transaction.atomic():
            qr.save()
    except IntegrityError as exc:
        raise QrConflict("Un QR actif existe déjà pour ce produit dans cette box.") from exc


def _locked(qr: QRCode) -> QRCode:
    return QRCode.objects.select_for_update(of=("self",)).select_related("box", "product").get(pk=qr.pk)


@transaction.atomic
def create_qr(
    *, box: Box, product: Product, user, note: str = "", request=None, instance: QRCode | None = None
) -> QRCode:
    """Nouveau QR actif pour un couple box–produit (un produit dans deux boxes = deux QR, R05)."""
    _check_destination(box, product)
    _check_free(box, product)
    qr = instance or QRCode()
    qr.box, qr.product, qr.note, qr.created_by = box, product, (note or "")[:255], user
    qr.code = unique_code(QRCode, "code", settings.QR_CODE_LENGTH)
    qr.is_active, qr.activated_at, qr.deactivated_at = True, timezone.now(), None
    _save_unique(qr)
    log_action(
        actor=user,
        action="qr.create",
        obj=qr,
        changes={"code": [None, qr.code], "box": [None, box], "product": [None, product]},
        request=request,
    )
    return qr


@transaction.atomic
def deactivate_qr(*, qr: QRCode, user, request=None) -> QRCode:
    qr = _locked(qr)
    if not qr.is_active:
        return qr
    qr.is_active, qr.deactivated_at = False, timezone.now()
    qr.save(update_fields=["is_active", "deactivated_at", "updated_at"])
    log_action(
        actor=user, action="qr.deactivate", obj=qr, changes={"is_active": [True, False]}, request=request
    )
    return qr


@transaction.atomic
def activate_qr(*, qr: QRCode, user, request=None) -> QRCode:
    qr = _locked(qr)
    if qr.is_active:
        return qr
    if qr.replaced_by_id:
        raise ConflictError("Ce QR a été remplacé : utilisez le nouveau code.", code="qr_replaced")
    _check_destination(qr.box, qr.product)
    _check_free(qr.box, qr.product, exclude=qr)
    qr.is_active, qr.activated_at, qr.deactivated_at = True, timezone.now(), None
    _save_unique(qr)
    log_action(
        actor=user, action="qr.activate", obj=qr, changes={"is_active": [False, True]}, request=request
    )
    return qr


@transaction.atomic
def regenerate_qr(*, qr: QRCode, user, request=None) -> QRCode:
    """Nouveau code pour la même destination ; l'ancien est désactivé (410) et pointe vers le nouveau."""
    old = _locked(qr)
    if old.replaced_by_id:
        raise ConflictError("Ce QR a déjà été remplacé.", code="qr_replaced")
    _check_destination(old.box, old.product)
    was_active = old.is_active
    old.is_active = False
    old.deactivated_at = old.deactivated_at if not was_active else timezone.now()
    old.save(update_fields=["is_active", "deactivated_at", "updated_at"])
    _check_free(old.box, old.product)
    new = QRCode(
        box=old.box,
        product=old.product,
        note=old.note,
        created_by=user,
        is_active=True,
        activated_at=timezone.now(),
        code=unique_code(QRCode, "code", settings.QR_CODE_LENGTH),
    )
    _save_unique(new)
    old.replaced_by = new
    old.save(update_fields=["replaced_by", "updated_at"])
    log_action(
        actor=user,
        action="qr.regenerate",
        obj=old,
        changes={"is_active": [was_active, False], "replaced_by": [None, new.code]},
        request=request,
    )
    log_action(
        actor=user,
        action="qr.create",
        obj=new,
        changes={"code": [None, new.code], "replaces": [None, old.code]},
        request=request,
    )
    return new


@transaction.atomic
def reassign_qr(
    *, qr: QRCode, user, box: Box | None = None, product: Product | None = None, request=None
) -> QRCode:
    """Même code imprimé, nouvelle destination. Les scans passés gardent leur box et leur produit."""
    qr = _locked(qr)
    target_box, target_product = box or qr.box, product or qr.product
    if (target_box.pk, target_product.pk) == (qr.box_id, qr.product_id):
        raise ValidationError({"non_field_errors": ["Indiquez une nouvelle box ou un nouveau produit."]})
    if qr.is_active:
        _check_destination(target_box, target_product)
        _check_free(target_box, target_product, exclude=qr)
    changes = {}
    if target_box.pk != qr.box_id:
        changes["box"] = [qr.box, target_box]
    if target_product.pk != qr.product_id:
        changes["product"] = [qr.product, target_product]
    qr.box, qr.product = target_box, target_product
    _save_unique(qr)
    log_action(actor=user, action="qr.reassign", obj=qr, changes=changes, request=request)
    return qr
