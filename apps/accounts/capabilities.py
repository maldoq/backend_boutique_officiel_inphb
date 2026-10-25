"""Rôles et capacités du personnel (cahier des charges §9, matrice C.6).

Un rôle = un groupe Django (code ci-dessous). Une capacité = un droit élémentaire déclaré dans le
code ; chaque vue d'administration déclare la capacité requise par méthode HTTP.
"""

from dataclasses import dataclass

CATALOG_VIEW = "catalog.view"
CATALOG_MANAGE = "catalog.manage"
STOCK_VIEW = "stock.view"
STOCK_MANAGE = "stock.manage"
ORDERS_VIEW = "orders.view"
ORDERS_MANAGE = "orders.manage"
PICKUP_MANAGE = "pickup.manage"
BOXES_VIEW = "boxes.view"
BOXES_MANAGE = "boxes.manage"
TRACKING_VIEW = "tracking.view"
ANALYTICS_VIEW = "analytics.view"
ANALYTICS_EXPORT = "analytics.export"
PROMOTIONS_MANAGE = "promotions.manage"  # Phase 2
CONTENT_MANAGE = "content.manage"  # Phase 2
PAYMENTS_VIEW = "payments.view"
USERS_MANAGE = "users.manage"
AUDIT_VIEW = "audit.view"
SETTINGS_MANAGE = "settings.manage"

# Ordre canonique (réponses JSON stables).
ALL_CAPABILITIES: tuple[str, ...] = (
    CATALOG_VIEW,
    CATALOG_MANAGE,
    STOCK_VIEW,
    STOCK_MANAGE,
    ORDERS_VIEW,
    ORDERS_MANAGE,
    PICKUP_MANAGE,
    BOXES_VIEW,
    BOXES_MANAGE,
    TRACKING_VIEW,
    ANALYTICS_VIEW,
    ANALYTICS_EXPORT,
    PROMOTIONS_MANAGE,
    CONTENT_MANAGE,
    PAYMENTS_VIEW,
    USERS_MANAGE,
    AUDIT_VIEW,
    SETTINGS_MANAGE,
)

CAPABILITY_LABELS: dict[str, str] = {
    CATALOG_VIEW: "Consulter le catalogue",
    CATALOG_MANAGE: "Gérer le catalogue",
    STOCK_VIEW: "Consulter les stocks",
    STOCK_MANAGE: "Ajuster les stocks",
    ORDERS_VIEW: "Consulter les commandes",
    ORDERS_MANAGE: "Traiter les commandes",
    PICKUP_MANAGE: "Gérer les points de retrait",
    BOXES_VIEW: "Consulter les boxes et QR codes",
    BOXES_MANAGE: "Gérer les boxes et QR codes",
    TRACKING_VIEW: "Consulter la traçabilité",
    ANALYTICS_VIEW: "Consulter les statistiques",
    ANALYTICS_EXPORT: "Exporter les statistiques",
    PROMOTIONS_MANAGE: "Gérer les codes promo",
    CONTENT_MANAGE: "Gérer les pages et contenus",
    PAYMENTS_VIEW: "Consulter les paiements",
    USERS_MANAGE: "Gérer les utilisateurs et rôles",
    AUDIT_VIEW: "Consulter le journal d'audit",
    SETTINGS_MANAGE: "Modifier les paramètres de la boutique",
}


@dataclass(frozen=True)
class Role:
    code: str
    label: str
    description: str
    capabilities: frozenset[str]


ADMIN_GENERAL = "ADMIN_GENERAL"
RESPONSABLE_BOUTIQUE = "RESPONSABLE_BOUTIQUE"
GESTIONNAIRE_CATALOGUE = "GESTIONNAIRE_CATALOGUE"
GESTIONNAIRE_COMMANDES = "GESTIONNAIRE_COMMANDES"
MARKETING = "MARKETING"
STATS_AUDIT = "STATS_AUDIT"

ROLES: dict[str, Role] = {
    role.code: role
    for role in (
        Role(
            ADMIN_GENERAL,
            "Administrateur général",
            "Accès complet à la plateforme, y compris les comptes du personnel et leurs rôles.",
            frozenset(ALL_CAPABILITIES),
        ),
        Role(
            RESPONSABLE_BOUTIQUE,
            "Responsable boutique",
            "Pilote la boutique : catalogue, stocks, commandes, boxes, statistiques et paramètres.",
            frozenset(ALL_CAPABILITIES) - {USERS_MANAGE},
        ),
        Role(
            GESTIONNAIRE_CATALOGUE,
            "Gestionnaire catalogue et stocks",
            "Gère les produits, variantes, photos et stocks.",
            frozenset({CATALOG_VIEW, CATALOG_MANAGE, STOCK_VIEW, STOCK_MANAGE}),
        ),
        Role(
            GESTIONNAIRE_COMMANDES,
            "Gestionnaire commandes et retraits",
            "Traite les commandes et les retraits Click & Collect au comptoir.",
            frozenset({CATALOG_VIEW, STOCK_VIEW, ORDERS_VIEW, ORDERS_MANAGE, PAYMENTS_VIEW}),
        ),
        Role(
            MARKETING,
            "Marketing",
            "Gère les boxes vitrées, les QR codes, les promotions et les contenus ; suit les statistiques.",
            frozenset(
                {
                    CATALOG_VIEW,
                    BOXES_VIEW,
                    BOXES_MANAGE,
                    TRACKING_VIEW,
                    ANALYTICS_VIEW,
                    ANALYTICS_EXPORT,
                    PROMOTIONS_MANAGE,
                    CONTENT_MANAGE,
                }
            ),
        ),
        Role(
            STATS_AUDIT,
            "Statistiques et audit",
            "Consulte l'activité, les statistiques et le journal d'audit, sans rien modifier.",
            frozenset(
                {
                    CATALOG_VIEW,
                    STOCK_VIEW,
                    ORDERS_VIEW,
                    BOXES_VIEW,
                    TRACKING_VIEW,
                    ANALYTICS_VIEW,
                    ANALYTICS_EXPORT,
                    PAYMENTS_VIEW,
                    AUDIT_VIEW,
                }
            ),
        ),
    )
}

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {code: role.capabilities for code, role in ROLES.items()}

_CACHE_ATTR = "_capabilities_cache"


def sort_capabilities(capabilities) -> list[str]:
    return [cap for cap in ALL_CAPABILITIES if cap in capabilities]


def user_roles(user) -> list[str]:
    """Codes des rôles de l'utilisateur (groupes reconnus), dans l'ordre de ROLES."""
    if not (user and user.is_authenticated):
        return []
    names = set(user.groups.values_list("name", flat=True))
    return [code for code in ROLES if code in names]


def user_capabilities(user) -> frozenset[str]:
    """Union des capacités des rôles ; le superutilisateur possède toutes les capacités."""
    if not (user and user.is_authenticated and user.is_active):
        return frozenset()
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    if user.is_superuser:
        capabilities = frozenset(ALL_CAPABILITIES)
    else:
        capabilities = frozenset().union(*(ROLE_CAPABILITIES[code] for code in user_roles(user)))
    setattr(user, _CACHE_ATTR, capabilities)
    return capabilities


def admin_caps(view_cap: str, manage_cap: str) -> dict[str, str]:
    """Capacités par méthode HTTP : lecture → view_cap, écriture → manage_cap."""
    for cap in (view_cap, manage_cap):
        if cap not in ALL_CAPABILITIES:
            raise ValueError(f"Capacité inconnue : {cap!r}")
    return {
        "GET": view_cap,
        "HEAD": view_cap,
        "OPTIONS": view_cap,
        "POST": manage_cap,
        "PUT": manage_cap,
        "PATCH": manage_cap,
        "DELETE": manage_cap,
    }
