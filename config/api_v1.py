"""Routes publiques /api/v1/ : chaque app ajoute ici son urls/public.py au fil des étapes."""

from django.urls import include, path, re_path

from apps.core.views import api_not_found

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.catalog.urls.public")),
    path("", include("apps.tracking.urls.public")),
    path("admin/", include("config.api_v1_admin")),
    # Toujours en dernier : toute route inconnue renvoie le format d'erreur C.5.
    re_path(r"^.*$", api_not_found),
]
