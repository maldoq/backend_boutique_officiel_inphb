from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from apps.core.request_context import get_client_platform, get_visitor_id
from apps.core.throttles import QrResolveIpThrottle, QrResolveThrottle
from apps.core.viewsets import PublicAPIView
from apps.tracking.serializers.public import QrResolutionSerializer, resolution_payload
from apps.tracking.services import resolve_qr

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
