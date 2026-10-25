"""Authentification du personnel : connexion, rotation et révocation des jetons, mot de passe."""

import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.exceptions import BusinessError
from apps.core.signals import emit_sensitive_change

from .tokens import issue_tokens, password_fingerprint_matches

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS_MESSAGE = "E-mail ou mot de passe incorrect."
SESSION_EXPIRED_MESSAGE = "Votre session a expiré. Veuillez vous reconnecter."


class InvalidCredentials(BusinessError):
    status_code, code = 401, "invalid_credentials"


class SessionExpired(BusinessError):
    status_code, code = 401, "authentication_failed"


def mask_email(email: str) -> str:
    """a.koffi@exemple.ci -> a***@exemple.ci (journaux sans donnée personnelle superflue)."""
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _is_active_staff(user) -> bool:
    return user is not None and user.is_active and user.is_staff


def login_staff(*, email: str, password: str, request=None, client_ip: str = "") -> tuple:
    """Vérifie les identifiants d'un membre actif du personnel ; renvoie (user, jetons)."""
    user = authenticate(request, email=(email or "").strip(), password=password)
    if not _is_active_staff(user):
        # Message générique : on ne révèle pas si le compte existe, est inactif ou non staff.
        logger.warning("Échec de connexion admin pour %s depuis %s", mask_email(email), client_ip or "?")
        raise InvalidCredentials(INVALID_CREDENTIALS_MESSAGE)
    update_last_login(None, user)
    return user, issue_tokens(user)


def _load_refresh(raw_refresh: str) -> RefreshToken:
    try:
        return RefreshToken(raw_refresh)  # vérifie signature, expiration et liste noire
    except TokenError as exc:
        raise SessionExpired(SESSION_EXPIRED_MESSAGE) from exc


def refresh_session(*, refresh: str) -> dict:
    """Rotation : nouveau couple de jetons, l'ancien refresh passe en liste noire."""
    token = _load_refresh(refresh)
    user_id = token.get(jwt_settings.USER_ID_CLAIM)
    user = get_user_model().objects.filter(**{jwt_settings.USER_ID_FIELD: user_id}).first()
    # Compte supprimé, désactivé, retiré du personnel ou mot de passe changé ⇒ session terminée.
    if not _is_active_staff(user) or not password_fingerprint_matches(token, user):
        token.blacklist()
        raise SessionExpired(SESSION_EXPIRED_MESSAGE)
    _, newly_blacklisted = token.blacklist()
    if not newly_blacklisted:
        # Deux rafraîchissements simultanés du même jeton : un seul obtient une nouvelle session.
        raise SessionExpired(SESSION_EXPIRED_MESSAGE)
    return issue_tokens(user)


def logout(*, refresh: str) -> None:
    """Révoque le refresh fourni (le jeton d'accès expire de lui-même sous 30 min au plus)."""
    _load_refresh(refresh).blacklist()


def revoke_all_sessions(user) -> int:
    """Met en liste noire tous les refresh encore valides de l'utilisateur."""
    pending = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in pending], ignore_conflicts=True
    )
    return len(pending)


@transaction.atomic
def change_password(*, user, current_password: str, new_password: str, request=None) -> dict:
    """Change le mot de passe, lève l'obligation de changement, ferme les autres sessions, audite."""
    if not user.check_password(current_password):
        raise ValidationError({"current_password": ["Mot de passe actuel incorrect."]})
    if current_password == new_password:
        raise ValidationError({"new_password": ["Le nouveau mot de passe doit être différent de l'actuel."]})
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)}) from exc
    was_temporary = user.must_change_password
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password", "updated_at"])
    revoked = revoke_all_sessions(user)
    emit_sensitive_change(
        sender=type(user),
        actor=user,
        action="user.password_change",
        obj=user,
        # Aucune valeur de mot de passe : le journal ne garde que le fait et ses effets.
        changes={"must_change_password": [was_temporary, False], "revoked_sessions": [None, revoked]},
        request=request,
    )
    return issue_tokens(user)
