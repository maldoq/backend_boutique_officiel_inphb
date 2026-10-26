"""Images des QR : lisibles par un vrai décodeur (OpenCV), SVG fidèle à la matrice, garde-fous."""

import re

import pytest
from django.test import override_settings

from apps.boxes import qr_images
from apps.boxes.tests.factories import QRCodeFactory
from apps.core.exceptions import ConflictError, ServiceUnavailableError

cv2 = pytest.importorskip("cv2", reason="opencv-python-headless (requirements/dev.txt) requis")
np = pytest.importorskip("numpy")

pytestmark = pytest.mark.django_db


def decode_png(data: bytes) -> str:
    """Décode avec les deux détecteurs d'OpenCV, sur deux cadrages (tel quel, ramené à ~600 px).

    Le détecteur par défaut rate environ 0,5 % de QR pourtant valides (y compris sans légende), que le
    détecteur « Aruco » lit sans difficulté ; les téléphones (ML Kit, ZXing) sont plus tolérants encore.
    Un QR réellement illisible échoue avec les deux détecteurs.
    """
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    scale = 600 / image.shape[1]
    framings = [image, cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)]
    for detector in (cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()):
        for framing in framings:
            if text := detector.detectAndDecode(framing)[0]:
                return text
    return ""


def svg_matrix(svg: str, size: int) -> list[list[bool]]:
    matrix = [[False] * size for _ in range(size)]
    for x, y, width in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", svg):
        for column in range(int(x), int(x) + int(width)):
            matrix[int(y)][column] = True
    return matrix


# Codes fixes (reproductible), dont ceux que le détecteur par défaut d'OpenCV ratait seul.
@pytest.mark.parametrize("code", ["Q4M8ZK2PTA", "PTSAUGVGAG", "SURJEG2R75", "4FG7J55GCC", "UJWXGF8XZD"])
@pytest.mark.parametrize(("size", "caption"), [(600, False), (600, True), (150, False), (2000, True)])
def test_png_lisible_par_un_decodeur(size, caption, code):
    qr = QRCodeFactory(
        code=code, product__name="Polo INP-HB Vert brodé édition spéciale", box__code="BOX-CENTRE-01"
    )
    data = qr_images.render_png(qr, size=size, caption=caption)
    assert data.startswith(b"\x89PNG")
    assert decode_png(data) == qr.public_url


def test_svg_identique_a_la_matrice_du_qr():
    qr = QRCodeFactory(product__name="Clé USB <32 Go> & co")
    svg = qr_images.render_svg(qr, size=600, caption=True)
    expected = qr_images.module_matrix(qr.public_url)
    assert svg_matrix(svg, len(expected)) == expected
    assert 'width="600"' in svg
    assert "Clé USB &lt;32 Go&gt; &amp; co" in svg  # texte échappé, accents conservés
    assert f"Code {qr.code}" in svg


def test_marge_de_silence_de_4_modules():
    matrix = qr_images.module_matrix("https://boutique.test/q/ABCDEFGHJK")
    border = qr_images.BORDER_MODULES
    assert not any(any(row[:border]) or any(row[-border:]) for row in matrix)
    assert not any(any(row) for row in matrix[:border] + matrix[-border:])


@pytest.mark.parametrize("font_path", ["system", None], ids=["police_complete", "repli_ascii"])
@pytest.mark.parametrize("width", [120, 300, 1500])
def test_legende_code_toujours_entier(font_path, width):
    from PIL import Image, ImageDraw

    qr = QRCodeFactory(
        product__name="Polo INP-HB Vert brodé – édition spéciale anniversaire 2026",
        box__code="BOX-CENTRE-AMPHI-NORD-01",
    )
    path = qr_images.caption_font_path() if font_path == "system" else None
    draw = ImageDraw.Draw(Image.new("L", (10, 10)))
    font, lines = qr_images.caption_layout(draw, qr, width=width, line_height=width * 0.11, font_path=path)
    expected = f"BOX-CENTRE-AMPHI-NORD-01 {'·' if path else '-'} Code {qr.code}"
    assert lines[1] == expected  # jamais tronqué : saisie manuelle de secours
    if path is None:
        assert all(line.isascii() for line in lines)  # pas de carrés vides sans police complète


def test_repli_ascii():
    assert qr_images.to_ascii("Vert brodé – édition · 2026 l’INP") == "Vert brode - edition - 2026 l'INP"


def test_nom_de_fichier_ascii():
    qr = QRCodeFactory(box__code="BOX-CENTRE-01", product__name="Polo INP-HB Vert")
    assert qr_images.filename(qr, "png") == "QR-BOX-CENTRE-01-polo-inp-hb-vert.png"


def test_qr_inactif_non_imprimable():
    with pytest.raises(ConflictError) as info:
        qr_images.render(QRCodeFactory(is_active=False), fmt="png")
    assert info.value.code == "qr_inactive"


@override_settings(DEBUG=False, PUBLIC_WEB_BASE_URL="http://localhost:4200")
def test_impression_refusee_sans_domaine_public_https():
    with pytest.raises(ServiceUnavailableError) as info:
        qr_images.render(QRCodeFactory(), fmt="svg")
    assert info.value.code == "public_url_not_configured"


@override_settings(DEBUG=True, PUBLIC_WEB_BASE_URL="http://localhost:4200")
def test_impression_autorisee_en_developpement():
    content, content_type = qr_images.render(QRCodeFactory(), fmt="png")
    assert content_type == "image/png" and content
