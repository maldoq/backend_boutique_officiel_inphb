from django.db.models import QuerySet

from .models import PickupPoint


def active_pickup_points() -> QuerySet[PickupPoint]:
    return PickupPoint.objects.filter(is_active=True).order_by("position", "name", "id")


def pickup_points_for_app_config(request) -> list[dict]:
    """Section « pickup_points » de GET /api/v1/app/config/ (branchée sans que core importe orders)."""
    return [
        {
            "id": point.pk,
            "code": point.code,
            "name": point.name,
            "address": point.address,
            "opening_hours": point.opening_hours,
        }
        for point in active_pickup_points()
    ]
