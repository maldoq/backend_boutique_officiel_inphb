"""Validation, ré-encodage (sans métadonnées EXIF) et miniatures des images téléversées (C.4, C.7)."""

import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
THUMBNAIL_WIDTH = 400
# Seules ces clés survivent au ré-encodage (rendu des couleurs et transparence) ; EXIF, XMP,
# commentaires et textes PNG sont supprimés.
_KEPT_INFO_KEYS = ("icc_profile", "transparency")
_SAVE_OPTIONS = {
    "JPEG": {"quality": 88, "optimize": True},
    "PNG": {"optimize": True},
    "WEBP": {"quality": 88},
}


@dataclass(frozen=True)
class ProcessedImage:
    content: ContentFile
    width: int
    height: int
    format: str


def _file_size(file) -> int:
    size = getattr(file, "size", None)
    if size is None:
        position = file.tell()
        file.seek(0, 2)
        size = file.tell()
        file.seek(position)
    return size


def validate_image(file) -> str:
    """Vérifie taille (5 Mo max), lisibilité et format (JPEG/PNG/WebP) ; renvoie le format Pillow."""
    if _file_size(file) > MAX_IMAGE_BYTES:
        raise ValidationError("L'image dépasse la taille maximale de 5 Mo.", code="image_too_large")
    try:
        file.seek(0)
        with warnings.catch_warnings():
            # Une image démesurée (« bombe de décompression ») est refusée au lieu d'être signalée.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file) as image:
                image_format = image.format
                image.verify()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ValidationError("Le fichier n'est pas une image valide.", code="invalid_image") from exc
    finally:
        file.seek(0)
    if image_format not in ALLOWED_FORMATS:
        raise ValidationError("Formats acceptés : JPEG, PNG ou WebP.", code="invalid_image_format")
    return image_format


def validate_uploaded_image(value) -> None:
    """Validateur de champ ImageField : contrôle les nouveaux fichiers, pas ceux déjà enregistrés."""
    if value and not getattr(value, "_committed", False):
        validate_image(value)


def _open_upright(file) -> Image.Image:
    file.seek(0)
    with Image.open(file) as source:
        image = ImageOps.exif_transpose(source)  # applique l'orientation avant de jeter l'EXIF
        image.load()
    file.seek(0)
    image.info = {key: value for key, value in image.info.items() if key in _KEPT_INFO_KEYS}
    return image


def reencode_image(file) -> ProcessedImage:
    """Valide puis ré-encode l'image dans son format d'origine, sans métadonnées."""
    image_format = validate_image(file)
    image = _open_upright(file)
    if image_format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format=image_format, **_SAVE_OPTIONS[image_format])
    name = f"{Path(getattr(file, 'name', '') or 'image').stem}.{ALLOWED_FORMATS[image_format]}"
    return ProcessedImage(ContentFile(buffer.getvalue(), name=name), image.width, image.height, image_format)


def make_thumbnail(file, width: int = THUMBNAIL_WIDTH) -> ContentFile:
    """Miniature WebP de `width` px de large (jamais agrandie), pour les listes du mobile."""
    image = _open_upright(file)
    if image.width > width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=80, method=4)
    name = f"{Path(getattr(file, 'name', '') or 'image').stem}.webp"
    return ContentFile(buffer.getvalue(), name=name)
