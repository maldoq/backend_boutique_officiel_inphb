from django.conf import settings


def absolute_media_url(request, file) -> str | None:
    """URL absolue d'un fichier (indispensable pour Flutter) ; None si aucun fichier.

    Avec une requête : hôte et schéma de la requête (https derrière Nginx via SECURE_PROXY_SSL_HEADER).
    Sans requête (e-mails) : API_PUBLIC_BASE_URL.
    """
    if not file:
        return None
    url = file.url
    if request is not None:
        return request.build_absolute_uri(url)
    return f"{settings.API_PUBLIC_BASE_URL}{url}"
