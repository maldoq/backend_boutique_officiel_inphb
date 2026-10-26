"""Écritures du catalogue (API d'administration et Django Admin) : validation, transaction, audit.

Règle D.4 : on ne supprime que ce qui n'a aucun historique. Tout objet référencé par une clé
PROTECT (mouvements de stock, et plus tard lignes de commande) déclenche 409 resource_in_use.
"""

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import Max
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError

from apps.audit.services import diff_instance, log_action
from apps.core.exceptions import ConflictError

from .models import Category, Product, ProductImage, ProductVariant, normalize_option
from .signals import initial_stock_requested

PRICE_FIELDS = {"price_xof", "compare_at_price_xof"}
CATEGORY_FIELDS = ("name", "slug", "parent", "description", "image", "position", "is_active")
PRODUCT_FIELDS = (
    "reference",
    "name",
    "slug",
    "category",
    "short_description",
    "description",
    "price_xof",
    "compare_at_price_xof",
    "is_active",
    "is_featured",
    "is_coming_soon",
    "seo_title",
    "seo_description",
)
VARIANT_FIELDS = (
    "sku",
    "size",
    "color",
    "model",
    "price_xof",
    "low_stock_threshold",
    "is_active",
    "position",
)
IMAGE_FIELDS = ("alt_text", "position", "is_main")


class ResourceInUse(ConflictError):
    code = "resource_in_use"


# --- Outils -------------------------------------------------------------------------


def _validated(instance: models.Model, *, exclude=None) -> None:
    """Règles du modèle (normalisation, contraintes, unicité) converties en erreurs d'API (400)."""
    try:
        instance.full_clean(exclude=exclude)
    except DjangoValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        ) from exc


def _apply(instance: models.Model, data: dict, fields) -> None:
    for name in fields:
        if name in data:
            setattr(instance, name, data[name])


def audit_changes(*, actor, obj, changes: dict, domain: str, request=None) -> None:
    """Prix dans « <domaine>.price_change », le reste dans « <domaine>.update »."""
    prices = {name: pair for name, pair in changes.items() if name in PRICE_FIELDS}
    others = {name: pair for name, pair in changes.items() if name not in PRICE_FIELDS}
    if prices:
        log_action(actor=actor, action=f"{domain}.price_change", obj=obj, changes=prices, request=request)
    if others:
        log_action(actor=actor, action=f"{domain}.update", obj=obj, changes=others, request=request)


def _delete(obj: models.Model, *, actor, action: str, message: str, request=None) -> None:
    with transaction.atomic():
        log_action(actor=actor, action=action, obj=obj, request=request)  # annulé si la suppression échoue
        try:
            obj.delete()
        except ProtectedError as exc:
            raise ResourceInUse(message) from exc


def _require_active_category(category: Category) -> None:
    if category is not None and not category.is_active:
        raise ValidationError({"category": ["Cette catégorie est inactive."]})


# --- Catégories ------------------------------------------------------------------------


@transaction.atomic
def create_category(*, data: dict, user, request=None) -> Category:
    category = Category()
    _apply(category, data, CATEGORY_FIELDS)
    _validated(category)
    category.save()
    log_action(
        actor=user,
        action="category.create",
        obj=category,
        changes={name: [None, getattr(category, name)] for name in ("name", "slug", "parent", "is_active")},
        request=request,
    )
    return category


@transaction.atomic
def update_category(*, category: Category, data: dict, user, request=None) -> Category:
    changes = diff_instance(category, data, [name for name in CATEGORY_FIELDS if name != "image"])
    _apply(category, data, CATEGORY_FIELDS)
    _validated(category)
    category.save()
    if changes:
        log_action(actor=user, action="category.update", obj=category, changes=changes, request=request)
    return category


def delete_category(*, category: Category, user, request=None) -> None:
    if category.children.exists():
        raise ResourceInUse("Cette catégorie contient des sous-catégories : désactivez-la plutôt.")
    _delete(
        category,
        actor=user,
        action="category.delete",
        request=request,
        message="Cette catégorie contient des produits : désactivez-la plutôt.",
    )


# --- Variantes ------------------------------------------------------------------------


def _option_key(data: dict) -> tuple:
    return tuple(normalize_option(data.get(name, "")).lower() for name in ("size", "color", "model"))


def create_variant(
    *, product: Product, data: dict, user, initial_stock: int = 0, request=None
) -> ProductVariant:
    """Crée une variante (stock 0) puis, si demandé, son stock initial via apps.inventory."""
    with transaction.atomic():
        variant = ProductVariant(product=product)
        _apply(variant, data, VARIANT_FIELDS)
        _validated(variant)
        variant.save()
        log_action(
            actor=user,
            action="variant.create",
            obj=variant,
            changes={
                name: [None, getattr(variant, name)] for name in ("sku", "label", "price_xof", "is_active")
            },
            request=request,
        )
        if initial_stock:
            if not initial_stock_requested.has_listeners():
                raise ImproperlyConfigured("Stock initial demandé mais apps.inventory n'est pas installé.")
            initial_stock_requested.send(
                sender=ProductVariant, variant=variant, quantity=initial_stock, user=user, request=request
            )
    return variant


@transaction.atomic
def update_variant(*, variant: ProductVariant, data: dict, user, request=None) -> ProductVariant:
    """Modifie une variante ; le SKU (imprimé sur les étiquettes) ne change que s'il est fourni."""
    data = {key: value for key, value in data.items() if key != "sku" or value}
    changes = diff_instance(variant, data, VARIANT_FIELDS)
    _apply(variant, data, VARIANT_FIELDS)
    _validated(variant)
    variant.save()
    if changes:
        audit_changes(actor=user, obj=variant, changes=changes, domain="variant", request=request)
    return variant


def delete_variant(*, variant: ProductVariant, user, request=None) -> None:
    if not ProductVariant.objects.filter(product_id=variant.product_id).exclude(pk=variant.pk).exists():
        raise ResourceInUse("Un produit garde toujours au moins une variante : désactivez-la plutôt.")
    _delete(
        variant,
        actor=user,
        action="variant.delete",
        request=request,
        message="Cette variante a un historique (stock, commandes) : désactivez-la plutôt.",
    )


# --- Produits ------------------------------------------------------------------------


def _set_related(product: Product, related_ids: list[int]) -> None:
    ids = list(dict.fromkeys(related_ids))
    if product.pk in ids:
        raise ValidationError({"related_product_ids": ["Un produit ne peut pas être associé à lui-même."]})
    found = set(Product.objects.filter(pk__in=ids).values_list("pk", flat=True))
    if missing := [pk for pk in ids if pk not in found]:
        raise ValidationError({"related_product_ids": [f"Produits inconnus : {missing}."]})
    product.related_products.set(ids)


def _check_variant_rows(variants: list[dict]) -> None:
    if not variants:
        raise ValidationError({"variants": ["Un produit doit avoir au moins une variante."]})
    seen: dict[tuple, int] = {}
    for index, row in enumerate(variants):
        key = _option_key(row)
        if key in seen:
            raise ValidationError(
                {
                    "variants": [
                        f"Ligne {index + 1} : même combinaison d'options que la ligne {seen[key] + 1}."
                    ]
                }
            )
        seen[key] = index


@transaction.atomic
def create_product(*, data: dict, variants: list[dict], user, related_ids=None, request=None) -> Product:
    """Produit + variantes + stocks initiaux en une transaction : tout ou rien."""
    _check_variant_rows(variants)
    product = Product(created_by=user)
    _apply(product, data, PRODUCT_FIELDS)
    _require_active_category(product.category if product.category_id else None)
    _validated(product)
    product.save()
    log_action(
        actor=user,
        action="product.create",
        obj=product,
        changes={
            name: [None, getattr(product, name)]
            for name in ("reference", "name", "category", "price_xof", "compare_at_price_xof", "is_active")
        },
        request=request,
    )
    for index, row in enumerate(variants):
        row = dict(row)
        initial_stock = row.pop("initial_stock", 0) or 0
        try:
            create_variant(product=product, data=row, initial_stock=initial_stock, user=user, request=request)
        except ValidationError as exc:
            raise ValidationError({"variants": {str(index): exc.detail}}) from exc
    if related_ids:
        _set_related(product, related_ids)
    product.refresh_search_text()
    return product


@transaction.atomic
def update_product(*, product: Product, data: dict, user, related_ids=None, request=None) -> Product:
    """Modifie les champs du produit (les variantes ont leurs propres routes)."""
    if "category" in data and data["category"] != product.category:
        _require_active_category(data["category"])
    changes = diff_instance(product, data, PRODUCT_FIELDS)
    _apply(product, data, PRODUCT_FIELDS)
    _validated(product)
    product.save()
    if related_ids is not None:
        before = sorted(product.related_products.values_list("pk", flat=True))
        _set_related(product, related_ids)
        after = sorted(product.related_products.values_list("pk", flat=True))
        if before != after:
            changes["related_product_ids"] = [before, after]
    if changes:
        audit_changes(actor=user, obj=product, changes=changes, domain="product", request=request)
    return product


def delete_product(*, product: Product, user, request=None) -> None:
    _delete(
        product,
        actor=user,
        action="product.delete",
        request=request,
        message="Ce produit a un historique (stock, commandes) : désactivez-le plutôt.",
    )


# --- Photos -------------------------------------------------------------------------


@transaction.atomic
def add_product_image(*, product: Product, image, alt_text: str = "", is_main: bool = False) -> ProductImage:
    """Photo ré-encodée (sans EXIF) + miniature, ajoutée en dernière position."""
    last = product.images.aggregate(last=Max("position"))["last"]
    photo = ProductImage(
        product=product,
        image=image,
        alt_text=alt_text,
        is_main=is_main,
        position=0 if last is None else last + 1,
    )
    _validated(photo)
    try:
        photo.save()
    except DjangoValidationError as exc:
        raise ValidationError({"image": exc.messages}) from exc
    return photo


@transaction.atomic
def update_product_image(*, image: ProductImage, data: dict) -> ProductImage:
    _apply(image, data, IMAGE_FIELDS)
    _validated(image, exclude=["image"])
    image.save()
    return image


def delete_product_image(*, image: ProductImage) -> None:
    image.delete()  # fichiers effacés après validation, image principale remplacée si besoin


@transaction.atomic
def reorder_images(*, product: Product, ids: list[int]) -> list[ProductImage]:
    current = set(product.images.values_list("pk", flat=True))
    if len(ids) != len(set(ids)) or set(ids) != current:
        raise ValidationError(
            {"ids": ["Indiquez exactement les photos de ce produit, chacune une seule fois."]}
        )
    for position, pk in enumerate(ids):
        ProductImage.objects.filter(pk=pk).update(position=position)
    return list(product.images.order_by("position", "id"))
