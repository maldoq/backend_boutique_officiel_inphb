"""Catalogue — API d'administration. Le stock exact est visible ici mais jamais modifiable."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.choices import Availability
from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.catalog.serializers.public import first_image
from apps.core.media import absolute_media_url


def _request(serializer):
    return serializer.context.get("request")


# --- Catégories ------------------------------------------------------------------------


class AdminCategorySerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), allow_null=True, required=False
    )
    image_url = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(read_only=True, default=0)
    children_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "parent",
            "description",
            "image",
            "image_url",
            "position",
            "is_active",
            "product_count",
            "children_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "slug": {"required": False, "validators": []},
            "image": {"write_only": True, "required": False},
        }
        validators = []  # unicité et règles du modèle vérifiées par le service (messages homogènes)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, category):
        return absolute_media_url(_request(self), category.image)


# --- Variantes ------------------------------------------------------------------------


class AdminVariantSerializer(serializers.ModelSerializer):
    """Lecture : stock exact, seuil effectif et disponibilité."""

    effective_price_xof = serializers.IntegerField(read_only=True)
    threshold = serializers.IntegerField(read_only=True, help_text="Seuil effectif (variante ou boutique).")
    availability = serializers.ChoiceField(choices=Availability.choices, read_only=True)
    availability_label = serializers.CharField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "product",
            "sku",
            "size",
            "color",
            "model",
            "label",
            "price_xof",
            "effective_price_xof",
            "stock_quantity",
            "low_stock_threshold",
            "threshold",
            "availability",
            "availability_label",
            "is_active",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class VariantWriteSerializer(serializers.Serializer):
    """Écriture d'une variante. stock_quantity n'existe pas ici : seul le service de stock le modifie."""

    sku = serializers.CharField(
        max_length=60,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Vide à la création : généré depuis la référence et les options.",
    )
    size = serializers.CharField(max_length=40, required=False, allow_blank=True)
    color = serializers.CharField(max_length=40, required=False, allow_blank=True)
    model = serializers.CharField(max_length=40, required=False, allow_blank=True)
    price_xof = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    low_stock_threshold = serializers.IntegerField(
        min_value=0, max_value=32767, required=False, allow_null=True
    )
    is_active = serializers.BooleanField(required=False)
    position = serializers.IntegerField(min_value=0, max_value=32767, required=False)


class VariantCreateSerializer(VariantWriteSerializer):
    initial_stock = serializers.IntegerField(min_value=0, max_value=1_000_000, required=False, default=0)


# --- Photos ---------------------------------------------------------------------------


class AdminProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "url", "thumbnail_url", "alt_text", "width", "height", "position", "is_main"]
        read_only_fields = ["id", "url", "thumbnail_url", "width", "height"]

    @extend_schema_field(serializers.URLField())
    def get_url(self, image):
        return absolute_media_url(_request(self), image.image)

    @extend_schema_field(serializers.URLField())
    def get_thumbnail_url(self, image):
        return absolute_media_url(_request(self), image.thumbnail) or self.get_url(image)


class ProductImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(help_text="JPEG, PNG ou WebP, 5 Mo maximum (EXIF supprimé).")
    alt_text = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    is_main = serializers.BooleanField(required=False, default=False)


class ProductImageUpdateSerializer(serializers.Serializer):
    alt_text = serializers.CharField(max_length=160, required=False, allow_blank=True)
    position = serializers.IntegerField(min_value=0, max_value=32767, required=False)
    is_main = serializers.BooleanField(required=False)


class ImageReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


# --- Produits ------------------------------------------------------------------------


class CategoryRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


class AdminProductListSerializer(serializers.ModelSerializer):
    category = CategoryRefSerializer()
    min_price_xof = serializers.IntegerField(source="price_from")
    availability = serializers.ChoiceField(source="availability_code", choices=Availability.choices)
    availability_label = serializers.SerializerMethodField()
    total_stock = serializers.IntegerField(help_text="Stock cumulé des variantes actives.")
    variant_count = serializers.IntegerField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "reference",
            "name",
            "slug",
            "category",
            "price_xof",
            "compare_at_price_xof",
            "min_price_xof",
            "is_active",
            "is_featured",
            "is_coming_soon",
            "availability",
            "availability_label",
            "total_stock",
            "variant_count",
            "thumbnail_url",
            "updated_at",
        ]
        read_only_fields = fields

    def get_availability_label(self, product) -> str:
        return Availability(product.availability_code).label

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, product):
        image = first_image(product)
        return (absolute_media_url(_request(self), image.thumbnail or image.image)) if image else None


class AdminProductDetailSerializer(AdminProductListSerializer):
    variants = AdminVariantSerializer(many=True, source="variants.all")
    images = AdminProductImageSerializer(many=True, source="images.all")
    related_product_ids = serializers.SerializerMethodField()
    created_by = serializers.EmailField(source="created_by.email", allow_null=True, default=None)

    class Meta(AdminProductListSerializer.Meta):
        fields = [
            *AdminProductListSerializer.Meta.fields,
            "short_description",
            "description",
            "seo_title",
            "seo_description",
            "variants",
            "images",
            "related_product_ids",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_related_product_ids(self, product):
        return sorted(p.pk for p in product.related_products.all())


class ProductWriteSerializer(serializers.Serializer):
    """Champs modifiables d'un produit. Les variantes ont leurs propres routes après la création."""

    reference = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=160)
    slug = serializers.CharField(
        max_length=180,
        required=False,
        allow_blank=True,
        help_text="Généré si vide. Le modifier casse les liens et QR déjà diffusés.",
    )
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    short_description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    price_xof = serializers.IntegerField(min_value=1)
    compare_at_price_xof = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    is_featured = serializers.BooleanField(required=False)
    is_coming_soon = serializers.BooleanField(required=False)
    seo_title = serializers.CharField(max_length=70, required=False, allow_blank=True)
    seo_description = serializers.CharField(max_length=160, required=False, allow_blank=True)
    related_product_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class ProductCreateSerializer(ProductWriteSerializer):
    variants = VariantCreateSerializer(
        many=True, allow_empty=False, help_text="Au moins une variante (« Standard » si aucune option)."
    )
