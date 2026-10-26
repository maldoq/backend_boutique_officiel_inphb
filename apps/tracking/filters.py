from django import forms
from django_filters import rest_framework as filters

from apps.core.choices import Channel

from .choices import EventType
from .models import TrackingEvent


class EventFilterForm(forms.Form):
    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError(
                {"date_to": "La date de fin doit être postérieure ou égale au début."}
            )
        return cleaned


class TrackingEventFilter(filters.FilterSet):
    """Pas de filtre par visiteur (R08). Dates incluses, au fuseau de la boutique (Africa/Abidjan)."""

    event_type = filters.ChoiceFilter(choices=EventType.choices)
    channel = filters.ChoiceFilter(choices=Channel.choices)
    box = filters.NumberFilter(field_name="box_id")
    qr = filters.NumberFilter(field_name="qr_id")
    product = filters.NumberFilter(field_name="product_id")
    date_from = filters.DateFilter(
        field_name="occurred_at", lookup_expr="date__gte", label="AAAA-MM-JJ (incluse)"
    )
    date_to = filters.DateFilter(
        field_name="occurred_at", lookup_expr="date__lte", label="AAAA-MM-JJ (incluse)"
    )

    class Meta:
        model = TrackingEvent
        fields = []
        form = EventFilterForm
