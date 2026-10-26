from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.tracking.models import TrackingEvent


class _QrRef(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()


class _BoxRef(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    label = serializers.CharField()


class _ProductRef(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class _VariantRef(serializers.Serializer):
    id = serializers.IntegerField()
    sku = serializers.CharField()
    label = serializers.CharField()


class AdminTrackingEventSerializer(serializers.ModelSerializer):
    """Aucune donnée personnelle ; identifiant de visite anonyme tronqué à 8 caractères."""

    event_type_label = serializers.CharField(source="get_event_type_display")
    visitor = serializers.SerializerMethodField()
    qr = _QrRef(allow_null=True)
    box = _BoxRef(allow_null=True)
    product = _ProductRef(allow_null=True)
    variant = _VariantRef(allow_null=True)

    class Meta:
        model = TrackingEvent
        fields = [
            "id",
            "event_type",
            "event_type_label",
            "occurred_at",
            "channel",
            "visitor",
            "qr",
            "box",
            "product",
            "variant",
            "quantity",
            "metadata",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_visitor(self, event) -> str:
        return str(event.visitor_id)[:8]
