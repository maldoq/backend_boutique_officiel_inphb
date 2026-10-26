from django.urls import path

from apps.inventory.views.admin import StockAdjustmentView, StockAlertsView, StockMovementViewSet

urlpatterns = [
    path(
        "variants/<int:pk>/stock-adjustments/", StockAdjustmentView.as_view(), name="admin-stock-adjustment"
    ),
    path("stock/movements/", StockMovementViewSet.as_view({"get": "list"}), name="admin-stock-movements"),
    path("stock/alerts/", StockAlertsView.as_view(), name="admin-stock-alerts"),
]
