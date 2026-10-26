from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.core.viewsets import PublicAPIView
from apps.orders.selectors import active_pickup_points
from apps.orders.serializers.public import PickupPointSerializer


class PickupPointListView(PublicAPIView):
    """Points de retrait actifs (non paginé)."""

    @extend_schema(
        tags=["Commandes"], summary="Points de retrait", responses=PickupPointSerializer(many=True)
    )
    def get(self, request):
        response = Response(PickupPointSerializer(active_pickup_points(), many=True).data)
        response["Cache-Control"] = "public, max-age=60"
        return response
