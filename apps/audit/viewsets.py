"""Vues d'administration auditables : bases à utiliser par les applications métier (étape 5 et suivantes).

Mêmes classes que apps.accounts.viewsets (JWT + HasCapability + capacités obligatoires), avec en
plus self.audit(action, obj, changes). Elles vivent ici car `accounts` précède `audit` (C.2).
"""

from apps.accounts import viewsets as base

from .mixins import AuditMixin


class AdminAPIView(AuditMixin, base.AdminAPIView):
    pass


class AdminViewSet(AuditMixin, base.AdminViewSet):
    pass


class AdminModelViewSet(AuditMixin, base.AdminModelViewSet):
    pass
