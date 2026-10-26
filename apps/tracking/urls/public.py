from django.urls import path

from apps.tracking.views.public import QrResolveView, TrackingEventBatchView, TrackingEventView

urlpatterns = [
    path("qr/<str:code>/resolve/", QrResolveView.as_view(), name="qr-resolve"),
    path("tracking/events/", TrackingEventView.as_view(), name="tracking-events"),
    path("tracking/events/batch/", TrackingEventBatchView.as_view(), name="tracking-events-batch"),
]
