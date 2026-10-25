"""Documentation OpenAPI de l'authentification JWT du projet (bouton « Authorize » de Swagger)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class StaffJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.JWTAuthentication"
    name = "jwtAuth"
