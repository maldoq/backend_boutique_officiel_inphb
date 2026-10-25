"""Limitation de débit par adresse IP des routes publiques sensibles (taux dans DEFAULT_THROTTLE_RATES).

L'IP est déterminée par DRF selon NUM_PROXIES (1 derrière Nginx en production).
"""

from rest_framework.throttling import SimpleRateThrottle


class IpRateThrottle(SimpleRateThrottle):
    """Compte les requêtes par IP pour la portée `scope` de la sous-classe."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginThrottle(IpRateThrottle):
    scope = "login"


class QrResolveThrottle(IpRateThrottle):
    scope = "qr_resolve"


class TrackingThrottle(IpRateThrottle):
    scope = "tracking"


class OrderCreateThrottle(IpRateThrottle):
    scope = "order_create"


class OrderLookupThrottle(IpRateThrottle):
    scope = "order_lookup"
