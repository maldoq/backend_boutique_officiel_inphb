"""Lectures du catalogue public (site web et application mobile).

Visibilité : produit actif dont la catégorie ET la catégorie parente éventuelle sont actives.
La disponibilité et le prix « à partir de » sont calculés EN BASE (filtres, tri et pagination
corrects, nombre de requêtes constant) avec exactement la règle de ProductVariant.availability.
"""

from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from .choices import Availability
from .models import Category, Product, ProductImage, ProductVariant

RELATED_LIMIT = 12
RELATED_FALLBACK_LIMIT = 4


def visible_categories() -> QuerySet[Category]:
    return Category.objects.filter(is_active=True).filter(Q(parent__isnull=True) | Q(parent__is_active=True))


def visible_products() -> QuerySet[Product]:
    return Product.objects.filter(is_active=True, category__is_active=True).filter(
        Q(category__parent__isnull=True) | Q(category__parent__is_active=True)
    )


def annotate_listing(queryset: QuerySet[Product], default_threshold: int) -> QuerySet[Product]:
    """Ajoute price_from, availability_code et has_options (calculés en base)."""
    active_variants = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
    threshold = Coalesce("low_stock_threshold", Value(default_threshold))
    cheapest = (
        active_variants.annotate(effective=Coalesce("price_xof", "product__price_xof"))
        .order_by("effective")
        .values("effective")[:1]
    )
    return queryset.annotate(
        price_from=Coalesce(Subquery(cheapest), F("price_xof")),
        availability_code=Case(
            When(is_coming_soon=True, then=Value(Availability.COMING_SOON)),
            When(
                Exists(active_variants.annotate(limit=threshold).filter(stock_quantity__gt=F("limit"))),
                then=Value(Availability.IN_STOCK),
            ),
            When(Exists(active_variants.filter(stock_quantity__gt=0)), then=Value(Availability.LOW_STOCK)),
            default=Value(Availability.OUT_OF_STOCK),
            output_field=CharField(),
        ),
        has_options=Exists(active_variants.exclude(size="", color="", model="")),
    )


def _images_prefetch() -> Prefetch:
    return Prefetch("images", queryset=ProductImage.objects.order_by("-is_main", "position", "id"))


def public_product_list(default_threshold: int) -> QuerySet[Product]:
    """Catalogue public : tri par défaut mis en avant, nom, puis id (pagination stable)."""
    return (
        annotate_listing(visible_products(), default_threshold)
        .select_related("category")
        .prefetch_related(_images_prefetch())
        .order_by("-is_featured", "name", "id")
    )


def public_product_detail_queryset(default_threshold: int) -> QuerySet[Product]:
    active_variants = ProductVariant.objects.filter(is_active=True).order_by("position", "id")
    return (
        annotate_listing(visible_products(), default_threshold)
        .select_related("category")
        .prefetch_related(_images_prefetch(), Prefetch("variants", queryset=active_variants))
    )


def related_products(product: Product, default_threshold: int) -> list[Product]:
    """Produits associés visibles ; à défaut, 4 produits visibles de la même catégorie."""
    base = public_product_list(default_threshold).exclude(pk=product.pk)
    explicit = list(base.filter(pk__in=product.related_products.values("pk"))[:RELATED_LIMIT])
    if explicit:
        return explicit
    return list(base.filter(category_id=product.category_id)[:RELATED_FALLBACK_LIMIT])


def category_tree() -> list[dict]:
    """Catégories visibles en arbre ; product_count inclut les produits des sous-catégories."""
    categories = list(visible_categories().order_by("position", "name", "id"))
    counts = dict(
        visible_products()
        .values_list("category_id")
        .annotate(total=Count("id"))
        .values_list("category_id", "total")
    )
    children_by_parent: dict[int, list[Category]] = {}
    for category in categories:
        if category.parent_id:
            children_by_parent.setdefault(category.parent_id, []).append(category)

    def node(category: Category) -> dict:
        children = [node(child) for child in children_by_parent.get(category.pk, [])]
        own = counts.get(category.pk, 0)
        return {
            "category": category,
            "product_count": own + sum(c["product_count"] for c in children),
            "children": children,
        }

    return [node(category) for category in categories if category.parent_id is None]
