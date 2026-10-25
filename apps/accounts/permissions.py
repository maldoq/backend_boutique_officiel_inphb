from rest_framework.permissions import BasePermission

from .capabilities import user_capabilities


def _is_active_staff(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


class IsActiveStaff(BasePermission):
    """Personnel connecté et actif, sans capacité particulière (profil, mot de passe, déconnexion)."""

    message = "Accès réservé au personnel de la boutique."

    def has_permission(self, request, view):
        return _is_active_staff(request.user)  # DRF renvoie 401 si non authentifié, 403 sinon


class HasCapability(BasePermission):
    """Autorise si l'utilisateur (staff, actif) possède la capacité requise pour la méthode HTTP.

    La vue déclare `required_capabilities` ({méthode: capacité}, « * » par défaut) et peut
    surcharger par action de ViewSet avec `action_capabilities`. Rien de déclaré ⇒ refus (R11).
    Tant qu'un mot de passe temporaire n'a pas été changé, toute route métier est refusée.
    """

    message = "Vous n'avez pas les droits nécessaires pour cette action."
    code = "permission_denied"

    def has_permission(self, request, view):
        user = request.user
        if not _is_active_staff(user):
            return False
        if user.must_change_password:
            self.message = "Vous devez changer votre mot de passe temporaire avant de continuer."
            self.code = "password_change_required"
            return False
        cap = self.required_capability(request, view)
        return cap is not None and cap in user_capabilities(user)

    @staticmethod
    def required_capability(request, view) -> str | None:
        action_caps = getattr(view, "action_capabilities", None) or {}
        required = getattr(view, "required_capabilities", None) or {}
        return (
            action_caps.get(getattr(view, "action", None))
            or required.get(request.method)
            or required.get("*")
        )
