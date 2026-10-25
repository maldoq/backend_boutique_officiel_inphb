"""Forme JSON des routes système (contrat partagé avec Angular et Flutter)."""

from rest_framework import serializers


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    database = serializers.ChoiceField(choices=["ok", "error"])
    version = serializers.CharField()
    time = serializers.DateTimeField()


class ShopSerializer(serializers.Serializer):
    name = serializers.CharField()
    slogan = serializers.CharField()
    contact_phone = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)


class MobileVersionSerializer(serializers.Serializer):
    min_supported_version = serializers.CharField()
    latest_version = serializers.CharField()


class FeaturesSerializer(serializers.Serializer):
    guest_checkout = serializers.BooleanField()
    online_payment = serializers.BooleanField()
    customer_accounts = serializers.BooleanField()
    delivery = serializers.BooleanField()
    promo_codes = serializers.BooleanField()


class PaymentConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    message = serializers.CharField(allow_blank=True)


class LimitsSerializer(serializers.Serializer):
    max_qty_per_line = serializers.IntegerField()
    max_lines_per_order = serializers.IntegerField()


class PickupPointSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    opening_hours = serializers.CharField(allow_blank=True)


class LegalPageSummarySerializer(serializers.Serializer):
    slug = serializers.CharField()
    title = serializers.CharField()
    url = serializers.CharField()


class AppConfigSerializer(serializers.Serializer):
    shop = ShopSerializer()
    currency = serializers.CharField()
    mobile = MobileVersionSerializer()
    features = FeaturesSerializer()
    payment = PaymentConfigSerializer()
    limits = LimitsSerializer()
    pickup_points = PickupPointSummarySerializer(many=True)
    legal_pages = LegalPageSummarySerializer(many=True)
    maintenance_mode = serializers.BooleanField()
