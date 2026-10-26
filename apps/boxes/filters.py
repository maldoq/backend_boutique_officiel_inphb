from django.db.models import Q
from django_filters import rest_framework as filters

from apps.core.filters import strict_boolean

from .models import Box, QRCode


class BoxFilter(filters.FilterSet):
    site = filters.CharFilter(field_name="site", lookup_expr="iexact")
    is_active = strict_boolean("is_active")
    search = filters.CharFilter(
        method="filter_search", max_length=100, label="Code, libellé, site, emplacement"
    )

    class Meta:
        model = Box
        fields = []

    def filter_search(self, queryset, name, value):
        value = value.strip()
        return queryset.filter(
            Q(code__icontains=value)
            | Q(label__icontains=value)
            | Q(site__icontains=value)
            | Q(location_details__icontains=value)
        )


class QRCodeFilter(filters.FilterSet):
    box = filters.NumberFilter(field_name="box_id")
    product = filters.NumberFilter(field_name="product_id")
    is_active = strict_boolean("is_active")
    search = filters.CharFilter(method="filter_search", max_length=100, label="Code QR ou nom du produit")

    class Meta:
        model = QRCode
        fields = []

    def filter_search(self, queryset, name, value):
        value = value.strip()
        compact = "".join(value.split()).upper()
        return queryset.filter(Q(code__contains=compact) | Q(product__name__icontains=value))
