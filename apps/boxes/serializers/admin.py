"""Boxes et QR codes — API d'administration (contrat G.4 pour les QR)."""

from urllib.parse import urlencode

from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.boxes.models import Box, QRCode
from apps.boxes.qr_images import DEFAULT_SIZE, FORMATS, MAX_SIZE, MIN_SIZE
from apps.boxes.signing import MAX_AGE_SECONDS, sign_image
from apps.catalog.models import Product


class BoxRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    label = serializers.CharField()
    site = serializers.CharField()


class ExposedProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class QrRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()


class AdminBoxSerializer(serializers.ModelSerializer):
    active_qr_count = serializers.IntegerField(read_only=True)
    qr_count = serializers.IntegerField(read_only=True)
    scans_count = serializers.IntegerField(read_only=True)
    products = serializers.SerializerMethodField(help_text="Produits exposés (QR actifs).")

    class Meta:
        model = Box
        fields = [
            "id",
            "code",
            "label",
            "site",
            "location_details",
            "is_active",
            "notes",
            "active_qr_count",
            "qr_count",
            "scans_count",
            "products",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(ExposedProductSerializer(many=True))
    def get_products(self, box):
        return ExposedProductSerializer([qr.product for qr in getattr(box, "active_qrs", [])], many=True).data


class BoxWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40, help_text="Ex. BOX-CENTRE-01 (normalisé en majuscules).")
    label = serializers.CharField(max_length=120)
    site = serializers.CharField(max_length=80)
    location_details = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class AdminQRCodeSerializer(serializers.ModelSerializer):
    public_url = serializers.URLField(read_only=True, help_text="URL encodée dans le QR imprimé.")
    image_png_url = serializers.SerializerMethodField(
        help_text=f"Lien signé, valable {MAX_AGE_SECONDS // 60} min."
    )
    image_svg_url = serializers.SerializerMethodField(
        help_text=f"Lien signé, valable {MAX_AGE_SECONDS // 60} min."
    )
    box = BoxRefSerializer()
    product = ExposedProductSerializer()
    replaced_by = QrRefSerializer(allow_null=True)
    scans_count = serializers.IntegerField(read_only=True, default=0)
    last_scanned_at = serializers.DateTimeField(read_only=True, allow_null=True, default=None)
    created_by = serializers.EmailField(source="created_by.email", allow_null=True, default=None)

    class Meta:
        model = QRCode
        fields = [
            "id",
            "code",
            "is_active",
            "public_url",
            "image_png_url",
            "image_svg_url",
            "box",
            "product",
            "note",
            "replaced_by",
            "scans_count",
            "last_scanned_at",
            "activated_at",
            "deactivated_at",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields

    def _image_url(self, qr, fmt) -> str:
        path = reverse("admin-qr-image", args=[qr.pk])
        query = urlencode({"format": fmt, "sig": sign_image(qr.pk, fmt)})
        request = self.context.get("request")
        url = f"{path}?{query}"
        return request.build_absolute_uri(url) if request else url

    @extend_schema_field(serializers.URLField())
    def get_image_png_url(self, qr):
        return self._image_url(qr, "png")

    @extend_schema_field(serializers.URLField())
    def get_image_svg_url(self, qr):
        return self._image_url(qr, "svg")


class QRCreateSerializer(serializers.Serializer):
    box_id = serializers.PrimaryKeyRelatedField(queryset=Box.objects.all())
    product_id = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class QRReassignSerializer(serializers.Serializer):
    box_id = serializers.PrimaryKeyRelatedField(queryset=Box.objects.all(), required=False)
    product_id = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Indiquez box_id et/ou product_id.")
        return attrs


class QRImageParamsSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=list(FORMATS), default="png")
    size = serializers.IntegerField(min_value=MIN_SIZE, max_value=MAX_SIZE, default=DEFAULT_SIZE)
    caption = serializers.BooleanField(default=False, help_text="Légende : produit, box et code en clair.")
    sig = serializers.CharField(required=False, help_text="Signature d'un lien temporaire (image_png_url…).")


class AuditEntrySerializer(serializers.Serializer):
    created_at = serializers.DateTimeField()
    action = serializers.CharField()
    actor_email = serializers.CharField()
    object_id = serializers.CharField()
    changes = serializers.DictField()


class QRHistorySerializer(serializers.Serializer):
    qr = QrRefSerializer()
    scans_count = serializers.IntegerField()
    predecessors = QrRefSerializer(many=True, help_text="QR remplacés, du plus ancien au plus récent.")
    successors = QrRefSerializer(many=True, help_text="QR remplaçants, du plus proche au plus récent.")
    entries = AuditEntrySerializer(
        many=True, help_text="Opérations sur ce QR, de la plus récente à la plus ancienne."
    )
