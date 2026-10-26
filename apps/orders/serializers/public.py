"""Panier, commande et suivi publics (contrat G.4)."""

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.choices import Availability
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.orders.choices import FulfillmentMethod
from apps.orders.models import CUSTOMER_NOTE_MAX_LENGTH, PickupPoint
from apps.orders.services import PAYMENT_DISABLED_MESSAGE


class PickupPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupPoint
        fields = ["id", "code", "name", "address", "instructions", "opening_hours", "phone"]
        read_only_fields = fields


# --- Entrées -------------------------------------------------------------------------------


class CartItemSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1000)
    source_qr_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=40,
        help_text="Code du QR scanné (objet attribution de la résolution).",
    )
    expected_unit_price_xof = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Prix affiché au client : s'il diffère, problème non bloquant price_changed.",
    )


class CartValidateSerializer(serializers.Serializer):
    items = CartItemSerializer(many=True, allow_empty=False, max_length=settings.MAX_LINES_PER_ORDER * 2)


class CustomerSerializer(serializers.Serializer):
    first_name = serializers.CharField(min_length=2, max_length=80)
    last_name = serializers.CharField(min_length=2, max_length=80)
    phone = serializers.CharField(max_length=30, help_text="Ex. 07 00 00 00 00 ou +225 07 00 00 00 00.")
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_email(self, value):
        return value.strip().lower()


class OrderLineSerializer(serializers.Serializer):
    """Aucun prix n'est accepté : le serveur seul fixe les montants (R01). Tout champ en trop est ignoré."""

    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1000)
    source_qr_code = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=40)


class OrderCreateSerializer(serializers.Serializer):
    customer = CustomerSerializer()
    fulfillment_method = serializers.ChoiceField(
        choices=FulfillmentMethod.choices, default=FulfillmentMethod.CLICK_AND_COLLECT
    )
    pickup_point_id = serializers.IntegerField(min_value=1)
    items = OrderLineSerializer(many=True, allow_empty=False, max_length=settings.MAX_LINES_PER_ORDER)
    customer_note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=CUSTOMER_NOTE_MAX_LENGTH
    )
    accept_terms = serializers.BooleanField(
        required=False, default=False, help_text="Obligatoire dès qu'une page CGV est publiée (Phase 2)."
    )

    def validate(self, attrs):
        attrs["customer_note"] = attrs.get("customer_note", "").strip()
        return attrs


class OrderLookupSerializer(serializers.Serializer):
    public_reference = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=30)


# --- Réponses ------------------------------------------------------------------------------


class CartIssueSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            "out_of_stock",
            "insufficient_stock",
            "product_unavailable",
            "quantity_limit_exceeded",
            "price_changed",
        ]
    )
    message = serializers.CharField()


class CartLineResultSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField()
    product_name = serializers.CharField(allow_null=True)
    variant_label = serializers.CharField(allow_null=True)
    unit_price_xof = serializers.IntegerField(allow_null=True)
    quantity = serializers.IntegerField()
    line_total_xof = serializers.IntegerField()
    availability = serializers.ChoiceField(choices=Availability.choices, allow_null=True)
    max_orderable_quantity = serializers.IntegerField()
    attribution_applied = serializers.BooleanField()
    issues = CartIssueSerializer(many=True)


class CartResultSerializer(serializers.Serializer):
    items = CartLineResultSerializer(many=True)
    subtotal_xof = serializers.IntegerField()
    discount_xof = serializers.IntegerField()
    fees_xof = serializers.IntegerField()
    total_xof = serializers.IntegerField()
    currency = serializers.CharField()
    is_valid = serializers.BooleanField(
        help_text="Aucun problème bloquant (price_changed n'est pas bloquant)."
    )
    maintenance_mode = serializers.BooleanField()


class OrderPickupPointSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    opening_hours = serializers.CharField()


class LineSourceSerializer(serializers.Serializer):
    qr_code = serializers.CharField()
    box_code = serializers.CharField()


class OrderLineResultSerializer(serializers.Serializer):
    product_name = serializers.CharField()
    variant_label = serializers.CharField()
    sku = serializers.CharField()
    unit_price_xof = serializers.IntegerField()
    quantity = serializers.IntegerField()
    line_total_xof = serializers.IntegerField()
    source = serializers.SerializerMethodField()

    @extend_schema_field(LineSourceSerializer(allow_null=True))
    def get_source(self, item):
        if not item.source_qr_id:
            return None
        return {"qr_code": item.source_qr.code, "box_code": item.source_box.code if item.source_box else ""}


class OrderSummarySerializer(serializers.Serializer):
    """Suivi public (GET /orders/{référence}/) : ni coordonnées ni code de retrait."""

    public_reference = serializers.CharField()
    status = serializers.CharField()
    status_label = serializers.CharField()
    payment_status = serializers.CharField()
    payment_status_label = serializers.CharField()
    fulfillment_method = serializers.CharField()
    pickup_point = OrderPickupPointSerializer()
    customer_name = serializers.CharField(source="masked_name", help_text="Nom masqué : « A. K. ».")
    items = OrderLineResultSerializer(many=True, source="items.all")
    subtotal_xof = serializers.IntegerField()
    discount_xof = serializers.IntegerField()
    shipping_fee_xof = serializers.IntegerField()
    total_xof = serializers.IntegerField()
    currency = serializers.CharField()
    created_at = serializers.DateTimeField()
    ready_at = serializers.DateTimeField(allow_null=True)
    collected_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)


class OrderCustomerSerializer(serializers.Serializer):
    first_name = serializers.CharField(source="customer_first_name")
    last_name = serializers.CharField(source="customer_last_name")
    phone = serializers.CharField(source="customer_phone")
    email = serializers.CharField(source="customer_email")


class OrderDetailSerializer(OrderSummarySerializer):
    """Commande créée ou retrouvée (référence + téléphone) : code de retrait et coordonnées."""

    customer_name = None
    payment_message = serializers.SerializerMethodField()
    pickup_code = serializers.CharField()
    pickup_qr_payload = serializers.SerializerMethodField(help_text="Contenu du QR de retrait à présenter.")
    customer = OrderCustomerSerializer(source="*")
    customer_note = serializers.CharField()

    def get_payment_message(self, order) -> str:
        return "" if order.payment_status == "paid" else PAYMENT_DISABLED_MESSAGE

    def get_pickup_qr_payload(self, order) -> str:
        return f"INPHB-PICKUP:{order.public_reference}:{order.pickup_code}"


class OrderWarningSerializer(serializers.Serializer):
    code = serializers.CharField()
    source_qr_code = serializers.CharField()
    variant_id = serializers.IntegerField()


class OrderCreatedSerializer(OrderDetailSerializer):
    warnings = OrderWarningSerializer(many=True)
