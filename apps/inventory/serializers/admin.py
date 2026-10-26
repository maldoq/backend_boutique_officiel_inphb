from rest_framework import serializers

from apps.inventory.choices import MANUAL_REASONS, StockReason
from apps.inventory.models import StockMovement
from apps.inventory.services import MAX_STOCK, NOTE_MAX_LENGTH


class StockAdjustmentSerializer(serializers.Serializer):
    """{"new_quantity": 25} ou {"delta": -2}, avec motif et note (règles métier dans le service)."""

    new_quantity = serializers.IntegerField(min_value=0, max_value=MAX_STOCK, required=False, allow_null=True)
    delta = serializers.IntegerField(
        min_value=-MAX_STOCK, max_value=MAX_STOCK, required=False, allow_null=True
    )
    reason = serializers.ChoiceField(choices=sorted(MANUAL_REASONS))
    note = serializers.CharField(max_length=NOTE_MAX_LENGTH, required=False, allow_blank=True, default="")


class ProductRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reference = serializers.CharField()
    name = serializers.CharField()


class VariantRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sku = serializers.CharField()
    label = serializers.CharField()
    product = ProductRefSerializer()


class StockMovementSerializer(serializers.ModelSerializer):
    variant = VariantRefSerializer()
    reason_label = serializers.CharField(source="get_reason_display")
    created_by = serializers.EmailField(source="created_by.email", allow_null=True, default=None)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "created_at",
            "variant",
            "delta",
            "reason",
            "reason_label",
            "balance_after",
            "note",
            "created_by",
        ]
        read_only_fields = fields


class StockAdjustmentResultSerializer(serializers.Serializer):
    movement = StockMovementSerializer()
    stock_quantity = serializers.IntegerField()
    availability = serializers.CharField()
    availability_label = serializers.CharField()


class StockAlertSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(source="id")
    sku = serializers.CharField()
    label = serializers.CharField()
    product = ProductRefSerializer()
    stock_quantity = serializers.IntegerField()
    threshold = serializers.IntegerField(source="alert_threshold")
    is_coming_soon = serializers.BooleanField(source="product.is_coming_soon")


class StockAlertCountsSerializer(serializers.Serializer):
    low_stock = serializers.IntegerField()
    out_of_stock = serializers.IntegerField()


class StockAlertsSerializer(serializers.Serializer):
    counts = StockAlertCountsSerializer()
    low_stock = StockAlertSerializer(many=True)
    out_of_stock = StockAlertSerializer(many=True)


REASON_CHOICES = StockReason.choices
