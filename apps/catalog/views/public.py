"""Catalogue public : routes sans authentification, servies au site web ET à l'application mobile."""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors
from apps.catalog.filters import ProductFilter
from apps.catalog.serializers.public import (
    CategoryTreeSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
)
from apps.core.models import SiteSettings

TAGS = ["Catalogue"]
PUBLIC_CACHE = "public, max-age=60"


class PublicCatalogMixin:
    authentication_classes = []
    permission_classes = [AllowAny]

    def site_settings(self) -> SiteSettings:
        """Paramètres lus une seule fois par requête (seuil de stock faible, nom de la boutique)."""
        if not hasattr(self, "_site_settings"):
            self._site_settings = SiteSettings.load()
        return self._site_settings

    @property
    def default_threshold(self) -> int:
        return self.site_settings().default_low_stock_threshold

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 200:
            response["Cache-Control"] = PUBLIC_CACHE
        return response


class CategoryListView(PublicCatalogMixin, APIView):
    """Arbre des catégories actives (non paginé)."""

    @extend_schema(tags=TAGS, summary="Catégories (arbre)", responses=CategoryTreeSerializer(many=True))
    def get(self, request):
        data = CategoryTreeSerializer(selectors.category_tree(), many=True, context={"request": request}).data
        return Response(data)


@extend_schema(tags=TAGS, summary="Catalogue (paginé, filtrable)")
class ProductListView(PublicCatalogMixin, generics.ListAPIView):
    serializer_class = ProductListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProductFilter

    def get_queryset(self):
        return selectors.public_product_list(self.default_threshold)


class ProductDetailView(PublicCatalogMixin, generics.RetrieveAPIView):
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return selectors.public_product_detail_queryset(self.default_threshold)

    @extend_schema(tags=TAGS, summary="Fiche produit")
    def get(self, request, *args, **kwargs):
        product = self.get_object()  # 404 not_found si inconnu, inactif ou catégorie masquée
        for variant in product.variants.all():
            variant.prime_default_threshold(self.default_threshold)
        context = {
            **self.get_serializer_context(),
            "related_products": selectors.related_products(product, self.default_threshold),
            "shop_name": self.site_settings().shop_name,
        }
        return Response(ProductDetailSerializer(product, context=context).data)


class RelatedProductListView(PublicCatalogMixin, generics.GenericAPIView):
    serializer_class = ProductListSerializer
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        return selectors.visible_products()

    @extend_schema(tags=TAGS, summary="Produits associés", responses=ProductListSerializer(many=True))
    def get(self, request, *args, **kwargs):
        product = self.get_object()
        related = selectors.related_products(product, self.default_threshold)
        return Response(ProductListSerializer(related, many=True, context={"request": request}).data)
