from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.core.exceptions import BusinessError, error_payload
from apps.core.request_context import get_app_version, get_client_platform, get_visitor_id
from apps.core.throttles import QrResolveIpThrottle, QrResolveThrottle, TrackingIpThrottle, TrackingThrottle
from apps.core.viewsets import PublicAPIView
from apps.tracking.serializers.events import (
    TrackingBatchResultSerializer,
    TrackingBatchSerializer,
    TrackingEventResultSerializer,
    TrackingEventSerializer,
)
from apps.tracking.serializers.public import QrResolutionSerializer, resolution_payload
from apps.tracking.services import RecordedEvent, record_event, resolve_qr

VISITOR_HEADER = OpenApiParameter(
    "X-Visitor-Id",
    location=OpenApiParameter.HEADER,
    required=False,
    description="Identifiant de visite anonyme (UUID v4). Absent ou invalide : généré et renvoyé.",
)
PLATFORM_HEADER = OpenApiParameter(
    "X-Client-Platform",
    location=OpenApiParameter.HEADER,
    required=False,
    enum=["web", "android", "ios"],
)


class QrResolveView(PublicAPIView):
    """Résout un QR scanné et enregistre le scan, attribué à la box d'origine."""

    throttle_classes = [QrResolveThrottle, QrResolveIpThrottle]

    @extend_schema(
        tags=["Traçabilité"],
        summary="Résoudre un QR code scanné",
        parameters=[VISITOR_HEADER, PLATFORM_HEADER],
        responses={
            200: QrResolutionSerializer,
            404: OpenApiResponse(description="qr_not_found : code inconnu"),
            410: OpenApiResponse(
                description="qr_inactive : QR, box ou produit désactivé (redirect_path « / »)"
            ),
        },
    )
    def get(self, request, code: str):
        visitor = get_visitor_id(request)
        resolution = resolve_qr(
            code=code, visitor_id=visitor.visitor_id, channel=get_client_platform(request)
        )
        response = Response(QrResolutionSerializer(resolution_payload(resolution, visitor.visitor_id)).data)
        response["Cache-Control"] = "no-store"  # chaque appel peut enregistrer un scan
        return response


def _record(data: dict, request, visitor_id) -> RecordedEvent:
    return record_event(
        event_type=data["event_type"],
        visitor_id=visitor_id,
        channel=get_client_platform(request),
        product=data["product"],
        variant=data["variant"],
        source_qr_code=data.get("source_qr_code"),
        quantity=data["quantity"],
        metadata=data.get("metadata"),
        app_version=get_app_version(request),
    )


class TrackingEventView(PublicAPIView):
    """Un événement du tunnel (consultation, panier, début de commande), attribué si prouvable."""

    throttle_classes = [TrackingThrottle, TrackingIpThrottle]

    @extend_schema(
        tags=["Traçabilité"],
        summary="Enregistrer un événement",
        parameters=[VISITOR_HEADER, PLATFORM_HEADER],
        request=TrackingEventSerializer,
        responses={201: TrackingEventResultSerializer, 200: TrackingEventResultSerializer},
    )
    def post(self, request):
        visitor = get_visitor_id(request)
        serializer = TrackingEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = _record(serializer.validated_data, request, visitor.visitor_id)
        payload = {
            "id": result.event.pk,
            "recorded": result.recorded,
            "attribution_applied": result.attribution_applied,
            "visitor_id": visitor.visitor_id,
        }
        code = status.HTTP_201_CREATED if result.recorded else status.HTTP_200_OK
        return Response(TrackingEventResultSerializer(payload).data, status=code)


class TrackingEventBatchView(PublicAPIView):
    """Jusqu'à 20 événements (mobile hors ligne), chacun validé et enregistré indépendamment."""

    throttle_classes = [TrackingThrottle, TrackingIpThrottle]

    @extend_schema(
        tags=["Traçabilité"],
        summary="Enregistrer un lot d'événements",
        parameters=[VISITOR_HEADER, PLATFORM_HEADER],
        request=TrackingBatchSerializer,
        responses=TrackingBatchResultSerializer,
    )
    def post(self, request):
        visitor = get_visitor_id(request)
        batch = TrackingBatchSerializer(data=request.data)
        batch.is_valid(raise_exception=True)
        accepted, rejected = 0, []
        for index, item in enumerate(batch.validated_data["events"]):
            serializer = TrackingEventSerializer(data=item)
            if not serializer.is_valid():
                rejected.append(
                    {
                        "index": index,
                        "error": error_payload(
                            "validation_error", "Certaines données sont invalides.", serializer.errors
                        )["error"],
                    }
                )
                continue
            try:
                with transaction.atomic():  # une erreur n'annule pas les autres événements du lot
                    _record(serializer.validated_data, request, visitor.visitor_id)
            except BusinessError as exc:
                rejected.append(
                    {"index": index, "error": error_payload(exc.code, exc.message, exc.details)["error"]}
                )
                continue
            accepted += 1
        payload = {"accepted": accepted, "rejected": rejected, "visitor_id": visitor.visitor_id}
        return Response(TrackingBatchResultSerializer(payload).data)
