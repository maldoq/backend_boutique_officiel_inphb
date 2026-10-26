from django.urls import path

from apps.orders.views.public import PickupPointListView

urlpatterns = [
    path("pickup-points/", PickupPointListView.as_view(), name="pickup-points"),
]
