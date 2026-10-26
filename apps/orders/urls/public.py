from django.urls import path

from apps.orders.views.public import (
    CartValidateView,
    OrderCreateView,
    OrderLookupView,
    OrderTrackingView,
    PickupPointListView,
)

urlpatterns = [
    path("pickup-points/", PickupPointListView.as_view(), name="pickup-points"),
    path("cart/validate/", CartValidateView.as_view(), name="cart-validate"),
    path("orders/", OrderCreateView.as_view(), name="orders-create"),
    path("orders/lookup/", OrderLookupView.as_view(), name="orders-lookup"),  # avant la route par référence
    path("orders/<str:public_reference>/", OrderTrackingView.as_view(), name="orders-tracking"),
]
