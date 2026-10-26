from django.urls import path

from apps.tracking.views.public import QrResolveView

urlpatterns = [
    path("qr/<str:code>/resolve/", QrResolveView.as_view(), name="qr-resolve"),
]
