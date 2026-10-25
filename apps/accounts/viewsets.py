"""Classes de base des vues d'administration (/api/v1/admin/) : JWT + HasCapability (R11)."""

from django.core.exceptions import ImproperlyConfigured
from rest_framework import viewsets
from rest_framework.views import APIView

from .authentication import JWTAuthentication
from .permissions import HasCapability


class CapabilityRequiredMixin:
    """Impose `required_capabilities` ou `action_capabilities` à chaque vue d'administration."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [HasCapability]
    required_capabilities: dict[str, str] = {}
    action_capabilities: dict[str, str] = {}

    def initial(self, request, *args, **kwargs):
        if not (self.required_capabilities or self.action_capabilities):
            raise ImproperlyConfigured(
                f"{type(self).__name__} doit déclarer required_capabilities ou action_capabilities."
            )
        super().initial(request, *args, **kwargs)


class AdminAPIView(CapabilityRequiredMixin, APIView):
    """Vue d'administration simple (actions, tableaux de bord)."""


class AdminViewSet(CapabilityRequiredMixin, viewsets.GenericViewSet):
    """ViewSet d'administration sans actions CRUD prédéfinies."""


class AdminModelViewSet(CapabilityRequiredMixin, viewsets.ModelViewSet):
    """ViewSet CRUD d'administration (pagination standard, filtres par défaut)."""
