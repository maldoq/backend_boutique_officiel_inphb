from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins

from apps.accounts.capabilities import TRACKING_VIEW
from apps.audit.viewsets import AdminViewSet
from apps.tracking.filters import TrackingEventFilter
from apps.tracking.models import TrackingEvent
from apps.tracking.serializers.admin import AdminTrackingEventSerializer


@extend_schema(tags=["Admin — Traçabilité"], summary="Journal des événements du tunnel")
class AdminTrackingEventViewSet(mixins.ListModelMixin, AdminViewSet):
    required_capabilities = {"GET": TRACKING_VIEW, "HEAD": TRACKING_VIEW, "OPTIONS": TRACKING_VIEW}
    queryset = TrackingEvent.objects.select_related("qr", "box", "product", "variant").order_by(
        "-occurred_at", "-id"
    )
    serializer_class = AdminTrackingEventSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = TrackingEventFilter
