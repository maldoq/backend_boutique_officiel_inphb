"""Réponse de la résolution d'un QR (contrat G.4)."""

from rest_framework import serializers


class ResolvedBoxSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    site = serializers.CharField()


class ResolvedProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class AttributionSerializer(serializers.Serializer):
    source_qr_code = serializers.CharField()
    source_box_code = serializers.CharField()
    source_product_id = serializers.IntegerField()
    scanned_at = serializers.DateTimeField()


class QrResolutionSerializer(serializers.Serializer):
    """Le client conserve `attribution` et renvoie source_qr_code avec chaque ligne de panier."""

    qr_code = serializers.CharField()
    box = ResolvedBoxSerializer()
    product = ResolvedProductSerializer()
    redirect_path = serializers.CharField()
    attribution = AttributionSerializer()
    visitor_id = serializers.UUIDField()


def resolution_payload(resolution, visitor_id) -> dict:
    qr = resolution.qr
    return {
        "qr_code": qr.code,
        "box": qr.box,
        "product": qr.product,
        "redirect_path": f"/produits/{qr.product.slug}?src={qr.code}",
        "attribution": {
            "source_qr_code": qr.code,
            "source_box_code": qr.box.code,
            "source_product_id": qr.product_id,
            "scanned_at": resolution.scanned_at.replace(microsecond=0),
        },
        "visitor_id": visitor_id,
    }
