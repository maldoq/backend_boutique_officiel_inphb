"""Stock — API d'administration : ajustements, historique des mouvements, alertes."""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.response import Response

from apps.accounts.capabilities import STOCK_MANAGE, STOCK_VIEW
from apps.audit.viewsets import AdminAPIView, AdminViewSet
from apps.catalog.models import ProductVariant
from apps.core.models import SiteSettings
from apps.inventory import selectors, services
from apps.inventory.filters import StockMovementFilter
from apps.inventory.models import StockMovement
from apps.inventory.serializers.admin import (
    StockAdjustmentResultSerializer,
    StockAdjustmentSerializer,
    StockAlertsSerializer,
    StockMovementSerializer,
)

TAGS = ["Admin — Stocks"]


class StockAdjustmentView(AdminAPIView):
    required_capabilities = {"POST": STOCK_MANAGE}

    @extend_schema(
        tags=TAGS,
        summary="Ajuster le stock d'une variante",
        request=StockAdjustmentSerializer,
        responses={201: StockAdjustmentResultSerializer},
    )
    def post(self, request, pk: int):
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        movement = services.adjust_stock(
            variant_id=pk, user=request.user, request=request, **serializer.validated_data
        )
        variant = ProductVariant.objects.select_related("product").get(pk=pk)
        movement = StockMovement.objects.select_related("variant__product", "created_by").get(pk=movement.pk)
        payload = {
            "movement": movement,
            "stock_quantity": variant.stock_quantity,
            "availability": variant.availability,
            "availability_label": variant.availability_label,
        }
        return Response(StockAdjustmentResultSerializer(payload).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS, summary="Historique des mouvements de stock")
class StockMovementViewSet(mixins.ListModelMixin, AdminViewSet):
    required_capabilities = {"GET": STOCK_VIEW, "HEAD": STOCK_VIEW, "OPTIONS": STOCK_VIEW}
    queryset = StockMovement.objects.select_related("variant__product", "created_by")
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = StockMovementFilter


class StockAlertsView(AdminAPIView):
    required_capabilities = {"GET": STOCK_VIEW}

    @extend_schema(tags=TAGS, summary="Alertes : stock faible et ruptures", responses=StockAlertsSerializer)
    def get(self, request):
        threshold = SiteSettings.load().default_low_stock_threshold
        low = list(selectors.low_stock_variants(threshold))
        out = list(selectors.out_of_stock_variants(threshold))
        payload = {
            "counts": {"low_stock": len(low), "out_of_stock": len(out)},
            "low_stock": low,
            "out_of_stock": out,
        }
        return Response(StockAlertsSerializer(payload).data)
