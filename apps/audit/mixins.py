from .services import log_action


class AuditMixin:
    """Ajoute self.audit(action, obj, changes) aux vues : auteur et IP tirés de la requête."""

    def audit(self, action: str, obj, changes=None):
        return log_action(
            actor=self.request.user, action=action, obj=obj, changes=changes, request=self.request
        )
