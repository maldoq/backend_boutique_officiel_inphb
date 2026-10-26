from rest_framework import serializers

from apps.orders.models import PickupPoint


class PickupPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupPoint
        fields = ["id", "code", "name", "address", "instructions", "opening_hours", "phone"]
        read_only_fields = fields
