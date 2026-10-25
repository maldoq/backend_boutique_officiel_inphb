"""Authentification de l'admin Angular : /api/v1/admin/auth/…"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.authentication import JWTAuthentication
from apps.accounts.permissions import IsActiveStaff
from apps.accounts.serializers.admin import (
    AdminProfileSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    RefreshSerializer,
    SessionSerializer,
    TokenPairSerializer,
)
from apps.core.request_context import get_client_ip
from apps.core.throttles import LoginThrottle

TAGS = ["Admin — Authentification"]


def _session_payload(user, tokens: dict) -> dict:
    return SessionSerializer({**tokens, "user": user}).data


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"  # jetons : jamais mis en cache
    return response


class LoginView(APIView):
    """Connexion du personnel (e-mail + mot de passe)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        tags=TAGS,
        summary="Connexion",
        request=LoginSerializer,
        responses={200: SessionSerializer, 401: OpenApiResponse(description="invalid_credentials")},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, tokens = services.login_staff(
            **serializer.validated_data,
            request=request,
            client_ip=get_client_ip(request) or "",
        )
        return _no_store(Response(_session_payload(user, tokens)))


class RefreshView(APIView):
    """Nouveau jeton d'accès (rotation : l'ancien refresh est révoqué)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=TAGS,
        summary="Rafraîchir la session",
        request=RefreshSerializer,
        responses={200: TokenPairSerializer},
    )
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = services.refresh_session(refresh=serializer.validated_data["refresh"])
        return _no_store(Response(TokenPairSerializer(tokens).data))


class LogoutView(APIView):
    """Déconnexion : le refresh suffit, même si le jeton d'accès a expiré."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(tags=TAGS, summary="Déconnexion", request=RefreshSerializer, responses={204: None})
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.logout(refresh=serializer.validated_data["refresh"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Profil courant + capacités (accessible même avec un mot de passe temporaire)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=TAGS, summary="Profil courant", responses=AdminProfileSerializer)
    def get(self, request):
        return Response(AdminProfileSerializer(request.user).data)


class ChangePasswordView(APIView):
    """Changement de mot de passe : ferme les autres sessions et renvoie de nouveaux jetons."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=TAGS,
        summary="Changer son mot de passe",
        request=ChangePasswordSerializer,
        responses={200: SessionSerializer},
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = services.change_password(user=request.user, request=request, **serializer.validated_data)
        return _no_store(Response(_session_payload(request.user, tokens)))
