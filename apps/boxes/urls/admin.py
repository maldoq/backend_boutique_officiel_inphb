from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.boxes.views.admin import AdminBoxViewSet, AdminQRCodeViewSet, QRImageView

router = SimpleRouter()
router.register("boxes", AdminBoxViewSet, basename="admin-box")
router.register("qr-codes", AdminQRCodeViewSet, basename="admin-qr")

urlpatterns = [
    path("qr-codes/<int:pk>/image/", QRImageView.as_view(), name="admin-qr-image"),
    *router.urls,
]
