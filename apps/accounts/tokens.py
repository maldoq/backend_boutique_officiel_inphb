"""Émission des jetons JWT du personnel.

Chaque jeton porte une empreinte du mot de passe (claim « pwd ») : changer ou réinitialiser le
mot de passe invalide immédiatement toutes les sessions existantes, jetons d'accès compris.
"""

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework_simplejwt.tokens import RefreshToken

PASSWORD_CLAIM = "pwd"


def password_fingerprint(user) -> str:
    """Empreinte courte et non réversible du hachage de mot de passe courant."""
    return salted_hmac("accounts.tokens.password", user.password).hexdigest()[:16]


def password_fingerprint_matches(token, user) -> bool:
    return constant_time_compare(str(token.get(PASSWORD_CLAIM, "")), password_fingerprint(user))


def access_lifetime_seconds() -> int:
    return int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())


def issue_tokens(user) -> dict:
    """Nouvelle paire access/refresh (le refresh est enregistré pour pouvoir être révoqué)."""
    refresh = RefreshToken.for_user(user)
    refresh[PASSWORD_CLAIM] = password_fingerprint(user)  # recopié dans le jeton d'accès
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "access_expires_in": access_lifetime_seconds(),
    }
