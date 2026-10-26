"""Boxes et QR codes — API d'administration (/api/v1/admin/boxes/, /api/v1/admin/qr-codes/)."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.permissions import BasePermission
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import JWTAuthentication
from apps.accounts.capabilities import BOXES_MANAGE, BOXES_VIEW, admin_caps
from apps.accounts.permissions import HasCapability
from apps.audit.models import AuditLog
from apps.audit.services import object_type_of
from apps.audit.viewsets import AdminModelViewSet, AdminViewSet
from apps.boxes import qr_images, selectors, services
from apps.boxes.filters import BoxFilter, QRCodeFilter
from apps.boxes.models import QRCode
from apps.boxes.serializers.admin import (
    AdminBoxSerializer,
    AdminQRCodeSerializer,
    BoxWriteSerializer,
    QRCreateSerializer,
    QRHistorySerializer,
    QRImageParamsSerializer,
    QRReassignSerializer,
)
from apps.boxes.signing import is_valid_image_signature

TAGS = ["Admin — Boxes et QR codes"]
BOXES_CAPS = admin_caps(BOXES_VIEW, BOXES_MANAGE)


# --- Boxes ------------------------------------------------------------------------------


@extend_schema(tags=TAGS)
class AdminBoxViewSet(AdminModelViewSet):
    required_capabilities = BOXES_CAPS
    serializer_class = AdminBoxSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = BoxFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return selectors.admin_box_queryset()

    def _respond(self, box, code=status.HTTP_200_OK):
        return Response(AdminBoxSerializer(self.get_queryset().get(pk=box.pk)).data, status=code)

    @extend_schema(request=BoxWriteSerializer, responses={201: AdminBoxSerializer})
    def create(self, request, *args, **kwargs):
        serializer = BoxWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        box = services.create_box(data=serializer.validated_data, user=request.user, request=request)
        return self._respond(box, status.HTTP_201_CREATED)

    @extend_schema(request=BoxWriteSerializer, responses=AdminBoxSerializer)
    def partial_update(self, request, *args, **kwargs):
        box = self.get_object()
        serializer = BoxWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_box(box=box, data=serializer.validated_data, user=request.user, request=request)
        return self._respond(box)

    def destroy(self, request, *args, **kwargs):
        services.delete_box(box=self.get_object(), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=AdminQRCodeSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="qr-codes")
    def qr_codes(self, request, pk=None):
        box = self.get_object()
        queryset = selectors.admin_qr_queryset().filter(box=box)
        return Response(
            AdminQRCodeSerializer(queryset, many=True, context=self.get_serializer_context()).data
        )


# --- QR codes ---------------------------------------------------------------------------


@extend_schema(tags=TAGS)
class AdminQRCodeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, AdminViewSet):
    """Pas de suppression : un QR se désactive (D.4)."""

    required_capabilities = BOXES_CAPS
    serializer_class = AdminQRCodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = QRCodeFilter

    def get_queryset(self):
        return selectors.admin_qr_queryset()

    def _respond(self, qr, code=status.HTTP_200_OK):
        fresh = selectors.admin_qr_queryset().get(pk=qr.pk)
        return Response(AdminQRCodeSerializer(fresh, context=self.get_serializer_context()).data, status=code)

    @extend_schema(request=QRCreateSerializer, responses={201: AdminQRCodeSerializer})
    def create(self, request, *args, **kwargs):
        serializer = QRCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        qr = services.create_qr(
            box=data["box_id"],
            product=data["product_id"],
            note=data["note"],
            user=request.user,
            request=request,
        )
        return self._respond(qr, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=AdminQRCodeSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._respond(services.deactivate_qr(qr=self.get_object(), user=request.user, request=request))

    @extend_schema(request=None, responses=AdminQRCodeSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._respond(services.activate_qr(qr=self.get_object(), user=request.user, request=request))

    @extend_schema(request=None, responses={201: AdminQRCodeSerializer})
    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        new = services.regenerate_qr(qr=self.get_object(), user=request.user, request=request)
        return self._respond(new, status.HTTP_201_CREATED)

    @extend_schema(request=QRReassignSerializer, responses=AdminQRCodeSerializer)
    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        qr = self.get_object()
        serializer = QRReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.reassign_qr(
            qr=qr, box=data.get("box_id"), product=data.get("product_id"), user=request.user, request=request
        )
        return self._respond(qr)

    @extend_schema(responses=QRHistorySerializer)
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        qr = self.get_object()
        predecessors, successors = selectors.qr_chain(qr)
        entries = AuditLog.objects.filter(object_type=object_type_of(qr), object_id=str(qr.pk)).order_by(
            "-created_at", "-id"
        )
        payload = {
            "qr": qr,
            "scans_count": qr.scans_count,
            "predecessors": predecessors,
            "successors": successors,
            "entries": entries,
        }
        return Response(QRHistorySerializer(payload).data)


# --- Image à imprimer --------------------------------------------------------------------


class IgnoreFormatQueryParam(DefaultContentNegotiation):
    """`format` désigne ici l'image (png/svg), pas le format de réponse de DRF."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class SignedLinkOrCapability(BasePermission):
    """Lien signé valide (balise <img>, téléchargement) OU personnel avec boxes.view."""

    def has_permission(self, request, view):
        token = request.query_params.get("sig")
        if token:
            fmt = request.query_params.get("format", "png")
            if is_valid_image_signature(token, view.kwargs["pk"], fmt):
                return True
            raise PermissionDenied("Ce lien a expiré : rechargez la page.", code="link_expired")
        return HasCapability().has_permission(request, view)


class QRImageView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [SignedLinkOrCapability]
    required_capabilities = {"GET": BOXES_VIEW}
    renderer_classes = [JSONRenderer]
    content_negotiation_class = IgnoreFormatQueryParam

    @extend_schema(
        tags=TAGS,
        summary="Image du QR à imprimer (PNG ou SVG)",
        parameters=[QRImageParamsSerializer],
        responses={
            (200, "image/png"): OpenApiTypes.BINARY,
            (200, "image/svg+xml"): OpenApiTypes.STR,
            409: OpenApiResponse(description="qr_inactive : un QR inactif ne s'imprime pas"),
            503: OpenApiResponse(description="public_url_not_configured : domaine public https manquant"),
        },
    )
    def get(self, request, pk: int):
        params = QRImageParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        qr = get_object_or_404(QRCode.objects.select_related("box", "product"), pk=pk)
        fmt = params.validated_data["format"]
        content, content_type = qr_images.render(
            qr, fmt=fmt, size=params.validated_data["size"], caption=params.validated_data["caption"]
        )
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{qr_images.filename(qr, fmt)}"'
        response["Cache-Control"] = "private, no-store"
        return response
