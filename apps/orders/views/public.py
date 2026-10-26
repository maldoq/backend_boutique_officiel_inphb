"""Panier, commande et suivi publics (site web et application mobile, sans authentification)."""

import re

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.exceptions import NotFoundError
from apps.core.request_context import get_client_platform, get_visitor_id, parse_visitor_id
from apps.core.throttles import (
    OrderCreateIpThrottle,
    OrderCreateThrottle,
    OrderLookupReferenceThrottle,
    OrderLookupThrottle,
)
from apps.core.viewsets import PublicAPIView
from apps.orders import services
from apps.orders.models import Order
from apps.orders.selectors import active_pickup_points
from apps.orders.serializers.public import (
    CartResultSerializer,
    CartValidateSerializer,
    OrderCreatedSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderLookupSerializer,
    OrderSummarySerializer,
    PickupPointSerializer,
)

TAGS = ["Commandes"]
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
IDEMPOTENCY_HEADER = OpenApiParameter(
    "Idempotency-Key",
    location=OpenApiParameter.HEADER,
    required=False,
    description="UUID recommandé : même clé + même contenu => même commande (200), sans doublon.",
)
VISITOR_HEADER = OpenApiParameter("X-Visitor-Id", location=OpenApiParameter.HEADER, required=False)
PLATFORM_HEADER = OpenApiParameter(
    "X-Client-Platform", location=OpenApiParameter.HEADER, required=False, enum=["web", "android", "ios"]
)
NOT_FOUND_MESSAGE = "Aucune commande ne correspond à ces informations."


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"  # coordonnées et code de retrait : jamais en cache
    return response


def _order_queryset():
    return Order.objects.select_related("pickup_point").prefetch_related(
        "items__source_qr", "items__source_box"
    )


class PickupPointListView(PublicAPIView):
    """Points de retrait actifs (non paginé)."""

    @extend_schema(tags=TAGS, summary="Points de retrait", responses=PickupPointSerializer(many=True))
    def get(self, request):
        response = Response(PickupPointSerializer(active_pickup_points(), many=True).data)
        response["Cache-Control"] = "public, max-age=60"
        return response


class CartValidateView(PublicAPIView):
    """Prix, stock et totaux serveur du panier, sans rien enregistrer."""

    @extend_schema(
        tags=TAGS,
        summary="Valider le panier",
        parameters=[VISITOR_HEADER],
        request=CartValidateSerializer,
        responses=CartResultSerializer,
    )
    def post(self, request):
        serializer = CartValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Le panier ne crée pas d'identifiant de visite : seul un identifiant déjà connu sert à l'attribution.
        visitor_id = parse_visitor_id(request.headers.get("X-Visitor-Id"))
        result = services.validate_cart(items=serializer.validated_data["items"], visitor_id=visitor_id)
        return _no_store(Response(CartResultSerializer(result).data))


class OrderCreateView(PublicAPIView):
    """Commande invitée Click & Collect (paiement non connecté : statut de paiement « unpaid »)."""

    throttle_classes = [OrderCreateThrottle, OrderCreateIpThrottle]

    @extend_schema(
        tags=TAGS,
        summary="Créer une commande",
        parameters=[IDEMPOTENCY_HEADER, VISITOR_HEADER, PLATFORM_HEADER],
        request=OrderCreateSerializer,
        responses={
            201: OrderCreatedSerializer,
            200: OrderCreatedSerializer,
            409: OpenApiResponse(description="insufficient_stock, product_unavailable, idempotency_conflict"),
            503: OpenApiResponse(description="maintenance_mode"),
        },
    )
    def post(self, request):
        key = (request.headers.get("Idempotency-Key") or "").strip() or None
        if key is not None and not _IDEMPOTENCY_KEY.match(key):
            raise ValidationError({"Idempotency-Key": ["8 à 64 caractères : lettres, chiffres, - ou _."]})
        visitor = get_visitor_id(request)
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.create_order(
            payload=serializer.validated_data,
            channel=get_client_platform(request),
            visitor_id=visitor.visitor_id,
            idempotency_key=key,
        )
        order = _order_queryset().get(pk=result.order.pk)
        order.warnings = result.warnings
        code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return _no_store(Response(OrderCreatedSerializer(order).data, status=code))


class OrderLookupView(PublicAPIView):
    """Suivi détaillé (code de retrait compris) : référence ET téléphone, jamais dans l'URL."""

    throttle_classes = [OrderLookupThrottle, OrderLookupReferenceThrottle]

    @extend_schema(
        tags=TAGS,
        summary="Retrouver sa commande",
        request=OrderLookupSerializer,
        responses={200: OrderDetailSerializer, 404: OpenApiResponse(description="not_found")},
    )
    def post(self, request):
        serializer = OrderLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.lookup_order(**serializer.validated_data)
        if order is None:  # même réponse que la référence existe ou non
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return _no_store(Response(OrderDetailSerializer(_order_queryset().get(pk=order.pk)).data))


class OrderTrackingView(PublicAPIView):
    """Suivi minimal par référence : statut, lignes et total, sans coordonnées ni code de retrait."""

    throttle_classes = [OrderLookupThrottle]

    @extend_schema(tags=TAGS, summary="Suivre une commande", responses=OrderSummarySerializer)
    def get(self, request, public_reference: str):
        order = (
            _order_queryset().filter(public_reference=services.normalize_reference(public_reference)).first()
        )
        if order is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return _no_store(Response(OrderSummarySerializer(order).data))
