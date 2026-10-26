"""Liens signés et temporaires vers les images de QR.

Un <img src> ou un lien de téléchargement dans Angular n'envoie pas le jeton JWT : l'API fournit
donc, aux seules personnes autorisées, des URL signées valables 10 minutes pour un QR et un format.
"""

from django.core import signing

SALT = "boxes.qr-image"
MAX_AGE_SECONDS = 600


def sign_image(qr_id: int, fmt: str) -> str:
    return signing.dumps({"q": qr_id, "f": fmt}, salt=SALT, compress=True)


def is_valid_image_signature(token: str, qr_id: int, fmt: str) -> bool:
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:  # SignatureExpired en hérite
        return False
    return payload == {"q": int(qr_id), "f": fmt}
