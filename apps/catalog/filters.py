from django import forms
from django.db.models import Q
from django_filters import rest_framework as filters

from apps.core.text import search_terms

from .choices import Availability
from .models import Product
from .selectors import visible_categories

ORDERINGS = {
    "price": ("price_from", "id"),
    "-price": ("-price_from", "-id"),
    "name": ("name", "id"),
    "-name": ("-name", "-id"),
    "created_at": ("created_at", "id"),
    "-created_at": ("-created_at", "-id"),
}


class ProductFilterForm(forms.Form):
    def clean(self):
        cleaned = super().clean()
        low, high = cleaned.get("min_price"), cleaned.get("max_price")
        if low is not None and high is not None and low > high:
            raise forms.ValidationError(
                {"max_price": "Le prix maximum doit être supérieur ou égal au minimum."}
            )
        return cleaned


class ProductFilter(filters.FilterSet):
    """Filtres du catalogue public. Prix : prix « à partir de » réellement payé."""

    search = filters.CharFilter(method="filter_search", max_length=100, label="Recherche (sans accents)")
    category = filters.CharFilter(
        method="filter_category", label="Slug de catégorie (sous-catégories incluses)"
    )
    min_price = filters.NumberFilter(field_name="price_from", lookup_expr="gte", min_value=0)
    max_price = filters.NumberFilter(field_name="price_from", lookup_expr="lte", min_value=0)
    availability = filters.ChoiceFilter(field_name="availability_code", choices=Availability.choices)
    # Strict : toute autre valeur que true/false est refusée (400) au lieu d'être ignorée.
    featured = filters.TypedChoiceFilter(
        field_name="is_featured",
        choices=[("true", "true"), ("false", "false")],
        coerce=lambda value: value == "true",
    )
    ordering = filters.ChoiceFilter(
        method="filter_ordering",
        choices=[(key, key) for key in ORDERINGS],
        label="Tri : price, -price, name, -name, created_at, -created_at",
    )

    class Meta:
        model = Product
        fields = []
        form = ProductFilterForm

    def filter_search(self, queryset, name, value):
        for term in search_terms(value):
            queryset = queryset.filter(search_text__contains=term)
        return queryset

    def filter_category(self, queryset, name, value):
        category = visible_categories().filter(slug=value).first()
        if category is None:
            return queryset.none()
        return queryset.filter(Q(category=category) | Q(category__parent=category))

    def filter_ordering(self, queryset, name, value):
        return queryset.order_by(*ORDERINGS[value])
