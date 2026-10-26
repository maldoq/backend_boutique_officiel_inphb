"""Catalogue — API d'administration (/api/v1/admin/…). Écritures par les services (validation, audit)."""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.capabilities import CATALOG_MANAGE, CATALOG_VIEW, admin_caps
from apps.audit.viewsets import AdminModelViewSet, AdminViewSet
from apps.catalog import selectors, services
from apps.catalog.filters import AdminCategoryFilter, AdminProductFilter
from apps.catalog.models import ProductImage, ProductVariant
from apps.catalog.serializers.admin import (
    AdminCategorySerializer,
    AdminProductDetailSerializer,
    AdminProductImageSerializer,
    AdminProductListSerializer,
    AdminVariantSerializer,
    ImageReorderSerializer,
    ProductCreateSerializer,
    ProductImageUpdateSerializer,
    ProductImageUploadSerializer,
    ProductWriteSerializer,
    VariantCreateSerializer,
    VariantWriteSerializer,
)
from apps.core.models import SiteSettings

CATALOG_CAPS = admin_caps(CATALOG_VIEW, CATALOG_MANAGE)
WRITE_METHODS = ["get", "post", "patch", "delete", "head", "options"]  # pas de PUT : PATCH partiel


class ThresholdMixin:
    @property
    def default_threshold(self) -> int:
        if not hasattr(self, "_default_threshold"):
            self._default_threshold = SiteSettings.load().default_low_stock_threshold
        return self._default_threshold

    def prime(self, variants):
        for variant in variants:
            variant.prime_default_threshold(self.default_threshold)
        return variants


@extend_schema(tags=["Admin — Catalogue"])
class AdminCategoryViewSet(AdminModelViewSet):
    required_capabilities = CATALOG_CAPS
    serializer_class = AdminCategorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdminCategoryFilter
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = WRITE_METHODS

    def get_queryset(self):
        return selectors.admin_category_queryset()

    def _respond(self, category, code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=category.pk)
        return Response(self.get_serializer(fresh).data, status=code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(
            data=serializer.validated_data, user=request.user, request=request
        )
        return self._respond(category, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = services.update_category(
            category=serializer.instance, data=serializer.validated_data, user=request.user, request=request
        )
        return self._respond(category)

    def destroy(self, request, *args, **kwargs):
        services.delete_category(category=self.get_object(), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Admin — Catalogue"])
class AdminProductViewSet(ThresholdMixin, AdminModelViewSet):
    required_capabilities = CATALOG_CAPS
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdminProductFilter
    http_method_names = WRITE_METHODS

    def get_queryset(self):
        return selectors.admin_product_queryset(self.default_threshold, detail=self.action != "list")

    def get_serializer_class(self):
        return {
            "list": AdminProductListSerializer,
            "create": ProductCreateSerializer,
            "partial_update": ProductWriteSerializer,
            "variants": VariantCreateSerializer,
            "images": ProductImageUploadSerializer,
            "reorder_images": ImageReorderSerializer,
        }.get(self.action, AdminProductDetailSerializer)

    def _detail(self, product, code=status.HTTP_200_OK):
        fresh = selectors.admin_product_queryset(self.default_threshold, detail=True).get(pk=product.pk)
        self.prime(fresh.variants.all())
        return Response(
            AdminProductDetailSerializer(fresh, context=self.get_serializer_context()).data, status=code
        )

    @extend_schema(responses=AdminProductDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        return self._detail(self.get_object())

    @extend_schema(request=ProductCreateSerializer, responses={201: AdminProductDetailSerializer})
    def create(self, request, *args, **kwargs):
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        variants, related = data.pop("variants"), data.pop("related_product_ids", None)
        product = services.create_product(
            data=data, variants=variants, related_ids=related, user=request.user, request=request
        )
        return self._detail(product, status.HTTP_201_CREATED)

    @extend_schema(request=ProductWriteSerializer, responses=AdminProductDetailSerializer)
    def partial_update(self, request, *args, **kwargs):
        product = self.get_object()
        serializer = ProductWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        related = data.pop("related_product_ids", None)
        services.update_product(
            product=product, data=data, related_ids=related, user=request.user, request=request
        )
        return self._detail(product)

    def destroy(self, request, *args, **kwargs):
        services.delete_product(product=self.get_object(), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(methods=["GET"], responses=AdminVariantSerializer(many=True))
    @extend_schema(methods=["POST"], request=VariantCreateSerializer, responses={201: AdminVariantSerializer})
    @action(detail=True, methods=["get", "post"])
    def variants(self, request, pk=None):
        product = self.get_object()
        if request.method == "GET":
            variants = self.prime(list(product.variants.all()))
            return Response(AdminVariantSerializer(variants, many=True).data)
        serializer = VariantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        initial_stock = data.pop("initial_stock", 0)
        variant = services.create_variant(
            product=product, data=data, initial_stock=initial_stock, user=request.user, request=request
        )
        variant.refresh_from_db()
        return Response(AdminVariantSerializer(self.prime([variant])[0]).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request={"multipart/form-data": ProductImageUploadSerializer},
        responses={201: AdminProductImageSerializer},
    )
    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def images(self, request, pk=None):
        product = self.get_object()
        serializer = ProductImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = services.add_product_image(product=product, **serializer.validated_data)
        return Response(
            AdminProductImageSerializer(image, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ImageReorderSerializer, responses=AdminProductImageSerializer(many=True))
    @action(detail=True, methods=["post"], url_path="images/reorder")
    def reorder_images(self, request, pk=None):
        product = self.get_object()
        serializer = ImageReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        images = services.reorder_images(product=product, ids=serializer.validated_data["ids"])
        return Response(
            AdminProductImageSerializer(images, many=True, context=self.get_serializer_context()).data
        )


@extend_schema(tags=["Admin — Catalogue"])
class AdminVariantViewSet(ThresholdMixin, mixins.RetrieveModelMixin, AdminViewSet):
    required_capabilities = CATALOG_CAPS
    queryset = ProductVariant.objects.select_related("product")
    serializer_class = AdminVariantSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_object(self):
        return self.prime([super().get_object()])[0]

    @extend_schema(request=VariantWriteSerializer, responses=AdminVariantSerializer)
    def partial_update(self, request, *args, **kwargs):
        variant = self.get_object()
        serializer = VariantWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_variant(
            variant=variant, data=serializer.validated_data, user=request.user, request=request
        )
        variant.refresh_from_db()
        return Response(AdminVariantSerializer(self.prime([variant])[0]).data)

    def destroy(self, request, *args, **kwargs):
        services.delete_variant(variant=self.get_object(), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Admin — Catalogue"])
class AdminProductImageViewSet(AdminViewSet):
    required_capabilities = {"*": CATALOG_MANAGE}
    queryset = ProductImage.objects.select_related("product")
    serializer_class = AdminProductImageSerializer
    http_method_names = ["patch", "delete", "options"]

    @extend_schema(request=ProductImageUpdateSerializer, responses=AdminProductImageSerializer)
    def partial_update(self, request, *args, **kwargs):
        image = self.get_object()
        serializer = ProductImageUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        image = services.update_product_image(image=image, data=serializer.validated_data)
        return Response(AdminProductImageSerializer(image, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        services.delete_product_image(image=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
