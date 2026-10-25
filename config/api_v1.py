"""Routes publiques /api/v1/ : chaque app ajoute ici son urls/public.py au fil des étapes."""

from django.urls import include, path

urlpatterns = [
    path("admin/", include("config.api_v1_admin")),
]
