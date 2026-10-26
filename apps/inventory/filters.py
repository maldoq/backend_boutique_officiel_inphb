from django import forms
from django_filters import rest_framework as filters

from .choices import StockReason
from .models import StockMovement


class MovementFilterForm(forms.Form):
    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError(
                {"date_to": "La date de fin doit être postérieure ou égale au début."}
            )
        return cleaned


class StockMovementFilter(filters.FilterSet):
    """Bornes de dates incluses, au fuseau de la boutique (Africa/Abidjan)."""

    variant = filters.NumberFilter(field_name="variant_id")
    product = filters.NumberFilter(field_name="variant__product_id")
    reason = filters.ChoiceFilter(choices=StockReason.choices)
    date_from = filters.DateFilter(
        field_name="created_at", lookup_expr="date__gte", label="AAAA-MM-JJ (incluse)"
    )
    date_to = filters.DateFilter(
        field_name="created_at", lookup_expr="date__lte", label="AAAA-MM-JJ (incluse)"
    )

    class Meta:
        model = StockMovement
        fields = []
        form = MovementFilterForm
