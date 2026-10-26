"""Routes d'administration /api/v1/admin/ : chaque app ajoute ici son urls/admin.py au fil des étapes."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.accounts.urls.admin")),
    path("", include("apps.catalog.urls.admin")),
    path("", include("apps.inventory.urls.admin")),
]
