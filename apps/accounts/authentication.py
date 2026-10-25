from rest_framework_simplejwt.authentication import JWTAuthentication as BaseJWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .tokens import password_fingerprint_matches


class JWTAuthentication(BaseJWTAuthentication):
    """JWT Bearer + rejet des jetons émis avant le dernier changement de mot de passe."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)  # refuse aussi les comptes inactifs ou supprimés
        if not password_fingerprint_matches(validated_token, user):
            raise AuthenticationFailed(
                "Votre session a expiré. Veuillez vous reconnecter.", code="authentication_failed"
            )
        return user
