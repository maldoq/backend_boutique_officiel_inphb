"""Limitation de débit des routes publiques sensibles (taux dans DEFAULT_THROTTLE_RATES).

L'IP est déterminée par DRF selon NUM_PROXIES (1 derrière Nginx en production). Sur le campus,
de nombreux visiteurs partagent la même IP publique : les routes très fréquentées (scan de QR)
combinent une limite par visiteur et un plafond large par IP.
"""

from rest_framework.throttling import SimpleRateThrottle

from .request_context import parse_visitor_id


class IpRateThrottle(SimpleRateThrottle):
    """Compte les requêtes par IP pour la portée `scope` de la sous-classe."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class VisitorRateThrottle(SimpleRateThrottle):
    """Compte par couple (IP, identifiant de visite). Sans identifiant valide (premier passage d'un
    nouveau visiteur), pas de limite ici : seul le plafond par IP s'applique, sinon tous les nouveaux
    visiteurs d'un même réseau partageraient un seul compteur."""

    def get_cache_key(self, request, view):
        visitor = parse_visitor_id(request.headers.get("X-Visitor-Id"))
        if visitor is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"{self.get_ident(request)}:{visitor}"}


class LoginThrottle(IpRateThrottle):
    scope = "login"


class QrResolveThrottle(VisitorRateThrottle):
    scope = "qr_resolve"


class QrResolveIpThrottle(IpRateThrottle):
    scope = "qr_resolve_ip"


class TrackingThrottle(VisitorRateThrottle):
    scope = "tracking"


class TrackingIpThrottle(IpRateThrottle):
    scope = "tracking_ip"


class OrderCreateThrottle(IpRateThrottle):
    scope = "order_create"


class OrderLookupThrottle(IpRateThrottle):
    scope = "order_lookup"
