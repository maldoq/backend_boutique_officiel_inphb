from django_filters import rest_framework as filters


def strict_boolean(field_name: str, **kwargs):
    """Filtre oui/non strict : toute valeur autre que true/false renvoie 400 (au lieu d'être ignorée)."""
    return filters.TypedChoiceFilter(
        field_name=field_name,
        choices=[("true", "true"), ("false", "false")],
        coerce=lambda value: value == "true",
        **kwargs,
    )
