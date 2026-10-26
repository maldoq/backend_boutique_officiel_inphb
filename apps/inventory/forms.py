from django import forms

from .choices import MANUAL_REASONS, StockReason
from .services import MAX_STOCK, NOTE_MAX_LENGTH


class StockAdjustmentForm(forms.Form):
    """Ajustement manuel : nouvelle quantité OU variation (les règles métier sont dans le service)."""

    new_quantity = forms.IntegerField(
        label="Nouvelle quantité",
        required=False,
        min_value=0,
        max_value=MAX_STOCK,
        help_text="Quantité réellement présente (inventaire).",
    )
    delta = forms.IntegerField(
        label="Ou variation",
        required=False,
        min_value=-MAX_STOCK,
        max_value=MAX_STOCK,
        help_text="Ex. +12 pour un réassort, -2 pour de la casse.",
    )
    reason = forms.ChoiceField(
        label="Motif",
        choices=[(value, label) for value, label in StockReason.choices if value in MANUAL_REASONS],
    )
    note = forms.CharField(
        label="Note",
        required=False,
        max_length=NOTE_MAX_LENGTH,
        help_text="Obligatoire pour un ajustement manuel ou une correction d'inventaire.",
    )
