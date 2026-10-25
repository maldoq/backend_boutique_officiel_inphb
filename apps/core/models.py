from django.db import models


class TimeStampedModel(models.Model):
    """Ajoute created_at (indexé) et updated_at à tous les modèles métier (D.4)."""

    created_at = models.DateTimeField("créé le", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        abstract = True
