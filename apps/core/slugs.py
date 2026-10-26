from django.db import models
from django.utils.text import slugify


def unique_slug(instance: models.Model, source: str, *, field: str = "slug") -> str:
    """Slug ASCII unique pour instance.field : « polo-inp-hb-vert », puis « -2 », « -3 »…

    La contrainte unique en base reste la garantie finale (accès concurrents).
    """
    model = type(instance)
    max_length = model._meta.get_field(field).max_length
    base = slugify(source)[:max_length].strip("-") or model._meta.model_name
    others = model._default_manager.all()
    if instance.pk is not None:
        others = others.exclude(pk=instance.pk)
    candidate, counter = base, 2
    while others.filter(**{field: candidate}).exists():
        suffix = f"-{counter}"
        candidate = f"{base[: max_length - len(suffix)].rstrip('-')}{suffix}"
        counter += 1
    return candidate
