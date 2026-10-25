from django.db import models


class Channel(models.TextChoices):
    """Canal client (en-tête X-Client-Platform), enregistré dans les événements et les commandes."""

    WEB = "web", "Web"
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
    UNKNOWN = "unknown", "Inconnu"
