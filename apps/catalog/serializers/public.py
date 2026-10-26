"""Catalogue public (contrat G.4). Jamais de stock exact ni de champ interne (coûts, auteur, seuils)."""

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.choices import Availability
from apps.core.media import absolute_media_url


def _request(serializer):
    return serializer.context.get("request")


def image_payload(request, image, *, full: bool = True) -> dict | None:
    if image is None:
        return None
    url = absolute_media_url(request, image.image)
    thumbnail = absolute_media_url(request, image.thumbnail) or url
    if not full:
        return {"thumbnail_url": thumbnail, "alt": image.alt_text}
    return {
        "url": url,
        "thumbnail_url": thumbnail,
        "alt": image.alt_text,
        "width": image.width,
        "height": image.height,
    }


def first_image(product):
    """Image principale (les images sont préchargées triées « principale d'abord »)."""
    images = product.images.all()
    return images[0] if images else None


# --- Schémas des objets imbriqués (documentation OpenAPI) ----------------------------


class ImageSerializer(serializers.Serializer):
    url = serializers.URLField()
    thumbnail_url = serializers.URLField()
    alt = serializers.CharField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()


class ProductImageSerializer(ImageSerializer):
    id = serializers.IntegerField()
    is_main = serializers.BooleanField()


class ThumbnailSerializer(serializers.Serializer):
    thumbnail_url = serializers.URLField()
    alt = serializers.CharField()


class CategorySummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class OptionsSerializer(serializers.Serializer):
    sizes = serializers.ListField(child=serializers.CharField())
    colors = serializers.ListField(child=serializers.CharField())
    models = serializers.ListField(child=serializers.CharField())


class SeoSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField()
    canonical_path = serializers.CharField()


# --- Catégories ---------------------------------------------------------------------


class CategoryTreeSerializer(serializers.Serializer):
    """Nœud de l'arbre {category, product_count, children} produit par selectors.category_tree()."""

    id = serializers.IntegerField(source="category.id")
    slug = serializers.CharField(source="category.slug")
    name = serializers.CharField(source="category.name")
    description = serializers.CharField(source="category.description")
    image_url = serializers.SerializerMethodField()
    product_count = serializers.IntegerField()
    children = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, node):
        return absolute_media_url(_request(self), node["category"].image)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_children(self, node):
        return CategoryTreeSerializer(node["children"], many=True, context=self.context).data


# --- Produits -----------------------------------------------------------------------


class ProductCardMixin(serializers.Serializer):
    """Champs calculés en base par selectors.annotate_listing()."""

    category = CategorySummarySerializer()
    min_price_xof = serializers.IntegerField(
        source="price_from", help_text="Prix « à partir de » réellement payé."
    )
    is_on_sale = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    availability = serializers.ChoiceField(source="availability_code", choices=Availability.choices)
    availability_label = serializers.SerializerMethodField()

    def get_is_on_sale(self, product) -> bool:
        return product.compare_at_price_xof is not None and product.compare_at_price_xof > product.price_from

    def get_currency(self, product) -> str:
        return "XOF"

    def get_availability_label(self, product) -> str:
        return Availability(product.availability_code).label


class ProductListSerializer(ProductCardMixin, serializers.Serializer):
    """Carte produit des listes : légère (ni description longue ni variantes)."""

    id = serializers.IntegerField()
    slug = serializers.CharField()
    reference = serializers.CharField()
    name = serializers.CharField()
    short_description = serializers.CharField()
    price_xof = serializers.IntegerField()
    compare_at_price_xof = serializers.IntegerField(allow_null=True)
    main_image = serializers.SerializerMethodField()
    is_coming_soon = serializers.BooleanField()
    has_variants = serializers.BooleanField(source="has_options", help_text="Au moins une option à choisir.")

    @extend_schema_field(ImageSerializer(allow_null=True))
    def get_main_image(self, product):
        return image_payload(_request(self), first_image(product))


class RelatedProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    price_xof = serializers.IntegerField()
    min_price_xof = serializers.IntegerField(source="price_from")
    main_image = serializers.SerializerMethodField()

    @extend_schema_field(ThumbnailSerializer(allow_null=True))
    def get_main_image(self, product):
        return image_payload(_request(self), first_image(product), full=False)


class VariantSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sku = serializers.CharField()
    label = serializers.CharField()
    size = serializers.CharField()
    color = serializers.CharField()
    model = serializers.CharField()
    price_xof = serializers.IntegerField(source="effective_price_xof")
    availability = serializers.CharField()
    availability_label = serializers.CharField()
    max_orderable_quantity = serializers.SerializerMethodField()

    def get_max_orderable_quantity(self, variant) -> int:
        if variant.availability in (Availability.OUT_OF_STOCK, Availability.COMING_SOON):
            return 0
        return min(variant.stock_quantity, settings.MAX_QTY_PER_LINE)


class ProductDetailSerializer(ProductListSerializer):
    description = serializers.CharField()
    images = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()
    variants = VariantSerializer(many=True, source="variants.all")
    related_products = serializers.SerializerMethodField()
    seo = serializers.SerializerMethodField()

    @extend_schema_field(ProductImageSerializer(many=True))
    def get_images(self, product):
        request = _request(self)
        return [
            {"id": image.id, **image_payload(request, image), "is_main": image.is_main}
            for image in product.images.all()
        ]

    @extend_schema_field(OptionsSerializer)
    def get_options(self, product):
        variants = product.variants.all()  # actives, dans l'ordre défini dans l'admin
        return {
            key: list(dict.fromkeys(getattr(v, attr) for v in variants if getattr(v, attr)))
            for key, attr in (("sizes", "size"), ("colors", "color"), ("models", "model"))
        }

    @extend_schema_field(RelatedProductSerializer(many=True))
    def get_related_products(self, product):
        related = self.context.get("related_products", [])
        return RelatedProductSerializer(related, many=True, context=self.context).data

    @extend_schema_field(SeoSerializer)
    def get_seo(self, product):
        shop_name = self.context.get("shop_name", "Boutique INP-HB")
        return {
            "title": product.seo_title or f"{product.name} | {shop_name}",
            "description": product.seo_description or product.short_description,
            "canonical_path": f"/produits/{product.slug}",
        }
