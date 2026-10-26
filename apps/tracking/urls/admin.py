from django.urls import path

from apps.tracking.views.admin import AdminTrackingEventViewSet

urlpatterns = [
    path(
        "tracking/events/", AdminTrackingEventViewSet.as_view({"get": "list"}), name="admin-tracking-events"
    ),
]
