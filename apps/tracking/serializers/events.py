"""Événements envoyés par le site web et l'application mobile (POST /api/v1/tracking/events/…)."""

from django.conf import settings
from rest_framework import serializers

from apps.catalog.models import ProductVariant
from apps.catalog.selectors import visible_products
from apps.tracking.choices import (
    CLIENT_EVENTS,
    PRODUCT_REQUIRED,
    SERVER_ONLY_EVENTS,
    VARIANT_REQUIRED,
    EventType,
)

MAX_BATCH_SIZE = 20


class TrackingEventSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(
        choices=EventType.choices, help_text="product_view, add_to_cart, remove_from_cart, checkout_started"
    )
    product_id = serializers.IntegerField(required=False, allow_null=True)
    product_slug = serializers.SlugField(required=False, allow_blank=True, max_length=180)
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    source_qr_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=40,
        help_text="Code du QR scanné (objet attribution de la résolution).",
    )
    box_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=40,
        help_text="Accepté pour compatibilité, toujours ignoré (R06).",
    )
    # JSONField (et non DictField) : une métadonnée mal formée est ignorée, l'événement reste enregistré.
    metadata = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="client_timestamp, app_version, screen ; le reste est supprimé.",
    )

    def validate_event_type(self, value):
        if value in SERVER_ONLY_EVENTS:
            raise serializers.ValidationError("Ce type d'événement est enregistré par le serveur uniquement.")
        if value not in CLIENT_EVENTS:
            raise serializers.ValidationError("Type d'événement inconnu.")
        return value

    def validate_quantity(self, value):
        if value is not None and value > settings.MAX_QTY_PER_LINE:
            raise serializers.ValidationError(f"Au plus {settings.MAX_QTY_PER_LINE}.")
        return value

    def validate(self, attrs):
        event_type = attrs["event_type"]
        product = self._product(attrs)
        if product is None and event_type in PRODUCT_REQUIRED:
            raise serializers.ValidationError({"product_id": ["Produit obligatoire pour cet événement."]})
        variant = None
        if event_type in VARIANT_REQUIRED:
            variant = self._variant(attrs, product)
            attrs["quantity"] = attrs.get("quantity") or 1
        elif attrs.get("variant_id"):
            variant = self._variant(attrs, product)
        if event_type not in VARIANT_REQUIRED:
            attrs["quantity"] = None
        attrs["product"], attrs["variant"] = product, variant
        return attrs

    def _product(self, attrs):
        product_id, slug = attrs.get("product_id"), attrs.get("product_slug")
        if not product_id and not slug:
            return None
        candidates = visible_products()
        product = (candidates.filter(pk=product_id) if product_id else candidates.filter(slug=slug)).first()
        if product is None:
            raise serializers.ValidationError({"product_id": ["Produit inconnu ou indisponible."]})
        if product_id and slug and product.slug != slug:
            raise serializers.ValidationError({"product_slug": ["Ne correspond pas à product_id."]})
        return product

    def _variant(self, attrs, product):
        variant_id = attrs.get("variant_id")
        if not variant_id:
            raise serializers.ValidationError({"variant_id": ["Variante obligatoire pour cet événement."]})
        variant = ProductVariant.objects.filter(pk=variant_id, product=product).first() if product else None
        if variant is None:
            raise serializers.ValidationError({"variant_id": ["Variante inconnue pour ce produit."]})
        return variant


class TrackingEventResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    recorded = serializers.BooleanField(help_text="False : doublon (même visiteur, même produit, 10 s).")
    attribution_applied = serializers.BooleanField()
    visitor_id = serializers.UUIDField()


class TrackingBatchSerializer(serializers.Serializer):
    events = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=MAX_BATCH_SIZE,
        help_text=f"1 à {MAX_BATCH_SIZE} événements, validés indépendamment.",
    )


class RejectedEventSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    error = serializers.DictField()


class TrackingBatchResultSerializer(serializers.Serializer):
    accepted = serializers.IntegerField()
    rejected = RejectedEventSerializer(many=True)
    visitor_id = serializers.UUIDField()
