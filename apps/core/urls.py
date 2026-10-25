from django.urls import path

from .views import AppConfigView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("app/config/", AppConfigView.as_view(), name="app-config"),
]
