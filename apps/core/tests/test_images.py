from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.images import MAX_IMAGE_BYTES, make_thumbnail, reencode_image, validate_image

EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F


def make_upload(fmt="JPEG", size=(1200, 800), name="photo.jpg", exif=None, mode="RGB"):
    buffer = BytesIO()
    image = Image.new(mode, size, color=(6, 113, 56) if mode == "RGB" else None)
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **kwargs)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_formats_acceptes(fmt):
    assert validate_image(make_upload(fmt=fmt, name=f"x.{fmt.lower()}")) == fmt


def test_format_refuse():
    with pytest.raises(ValidationError) as info:
        validate_image(make_upload(fmt="GIF", name="x.gif", mode="P"))
    assert info.value.code == "invalid_image_format"


def test_fichier_qui_n_est_pas_une_image():
    with pytest.raises(ValidationError) as info:
        validate_image(SimpleUploadedFile("faux.jpg", b"<?php echo 'x'; ?>", content_type="image/jpeg"))
    assert info.value.code == "invalid_image"


def test_image_trop_lourde():
    big = SimpleUploadedFile("lourd.jpg", b"0" * (MAX_IMAGE_BYTES + 1), content_type="image/jpeg")
    with pytest.raises(ValidationError) as info:
        validate_image(big)
    assert info.value.code == "image_too_large"


def test_reencodage_supprime_exif_et_applique_l_orientation():
    exif = Image.Exif()
    exif[EXIF_MAKE] = "AppareilSecret"
    exif[EXIF_ORIENTATION] = 6  # rotation de 90° : la photo doit être redressée
    upload = make_upload(size=(1200, 800), exif=exif.tobytes())

    processed = reencode_image(upload)

    with Image.open(BytesIO(processed.content.read())) as result:
        assert result.format == "JPEG"
        assert result.size == (800, 1200)
        assert "exif" not in result.info
        assert not result.getexif()
    assert (processed.width, processed.height) == (800, 1200)
    assert processed.content.name == "photo.jpg"


def test_miniature_400px_en_webp():
    thumb = make_thumbnail(make_upload(size=(1600, 1200)))
    with Image.open(BytesIO(thumb.read())) as result:
        assert result.format == "WEBP"
        assert result.size == (400, 300)
    assert thumb.name == "photo.webp"


def test_miniature_jamais_agrandie():
    thumb = make_thumbnail(make_upload(size=(300, 200)))
    with Image.open(BytesIO(thumb.read())) as result:
        assert result.size == (300, 200)
