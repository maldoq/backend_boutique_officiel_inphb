"""Images des QR codes à imprimer (PNG et SVG), légende facultative sous le QR.

Le QR encode public_url, correction d'erreur M (reste lisible un peu abîmé), marge de 4 modules.
La légende reprend le nom du produit, la box et le code en clair (saisie manuelle si la lecture échoue).
"""

import unicodedata
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import qrcode
from django.conf import settings
from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M

from apps.core.checks import is_public_https_url
from apps.core.exceptions import ConflictError, ServiceUnavailableError

from .models import QRCode

BORDER_MODULES = 4
MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 150, 2000, 600
FORMATS = {"png": "image/png", "svg": "image/svg+xml"}
CAPTION_RATIO = 0.22  # hauteur de la légende / largeur de l'image


def module_matrix(text: str) -> list[list[bool]]:
    """Matrice du QR, marge comprise (True = module noir)."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=BORDER_MODULES)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def ensure_printable(qr: QRCode) -> None:
    """Refuse d'imprimer un QR qui renverrait 410 ou pointerait vers une adresse inutilisable."""
    if not qr.is_active:
        raise ConflictError(
            "Ce QR code est inactif : une fois imprimé, il afficherait « QR inactif ».", code="qr_inactive"
        )
    if not settings.DEBUG and not is_public_https_url(settings.PUBLIC_WEB_BASE_URL):
        raise ServiceUnavailableError(
            "L'adresse publique du site (PUBLIC_WEB_BASE_URL) n'est pas un domaine https : "
            "impression des QR impossible.",
            code="public_url_not_configured",
        )


def caption_lines(qr: QRCode) -> list[str]:
    return [qr.product.name, f"{qr.box.code} · Code {qr.code}"]


def filename(qr: QRCode, fmt: str) -> str:
    """QR-BOX-CENTRE-01-polo-inp-hb-vert.png (ASCII uniquement)."""
    return f"QR-{qr.box.code}-{slugify(qr.product.slug)[:60]}.{fmt}"


# Polices complètes (accents, tirets typographiques) : réglage, DejaVu (Linux/Docker), Arial (Windows/macOS).
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)
MIN_FONT_SIZE = 8


@lru_cache(maxsize=1)
def caption_font_path() -> str | None:
    for candidate in (getattr(settings, "QR_CAPTION_FONT", ""), *FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _font(size: int, path: str | None):
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def to_ascii(text: str) -> str:
    """Repli sans police complète (jamais de carrés vides) : « brodé – 2026 » -> « brode - 2026 »."""
    text = text.replace("–", "-").replace("—", "-").replace("·", "-").replace("’", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    return (
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .encode("ascii", "ignore")
        .decode()
    )


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, width: float, ellipsis: str) -> str:
    """Tronque proprement un texte trop long."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(f"{text}{ellipsis}", font=font) > width:
        text = text[:-1]
    return f"{text.rstrip()}{ellipsis}"


def caption_layout(
    draw: ImageDraw.ImageDraw, qr: QRCode, *, width: float, line_height: float, font_path: str | None = None
):
    """(police, lignes) : la ligne « box · code » tient TOUJOURS en entier (saisie manuelle de secours),
    seul le nom du produit peut être raccourci."""
    lines = caption_lines(qr)
    if font_path is None:
        lines = [to_ascii(line) for line in lines]
    size = max(MIN_FONT_SIZE, int(line_height * 0.55))
    font = _font(size, font_path)
    while size > MIN_FONT_SIZE and draw.textlength(lines[1], font=font) > width:
        size -= 1
        font = _font(size, font_path)
    ellipsis = "…" if font_path else "..."
    return font, [_truncate(draw, lines[0], font, width, ellipsis), lines[1]]


def render_png(qr: QRCode, *, size: int = DEFAULT_SIZE, caption: bool = False) -> bytes:
    matrix = module_matrix(qr.public_url)
    count = len(matrix)
    module = max(1, size // count)
    side = module * count
    caption_height = round(side * CAPTION_RATIO) if caption else 0
    # Marge blanche sous la légende (comme la zone de silence) : le texte ne touche pas le bord.
    bottom_margin = BORDER_MODULES * module if caption else 0
    image = Image.new("L", (side, side + caption_height + bottom_margin), 255)
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                draw.rectangle([x * module, y * module, (x + 1) * module - 1, (y + 1) * module - 1], fill=0)
    if caption:  # sous la marge du QR : la zone de silence reste intacte pour la lecture
        line_height = caption_height / 2
        font, lines = caption_layout(
            draw,
            qr,
            width=side - 2 * BORDER_MODULES * module,
            line_height=line_height,
            font_path=caption_font_path(),
        )
        for index, line in enumerate(lines):
            draw.text((side / 2, side + (index + 0.5) * line_height), line, fill=0, font=font, anchor="mm")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_svg(qr: QRCode, *, size: int = DEFAULT_SIZE, caption: bool = False) -> str:
    """SVG vectoriel (impression à toute taille) : une ligne <path> par suite de modules noirs."""
    matrix = module_matrix(qr.public_url)
    count = len(matrix)
    caption_height = round(count * CAPTION_RATIO) if caption else 0
    total_height = count + caption_height + (BORDER_MODULES if caption else 0)  # marge sous la légende
    segments = []
    for y, row in enumerate(matrix):
        x = 0
        while x < count:
            if row[x]:
                start = x
                while x < count and row[x]:
                    x += 1
                segments.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    height_px = round(size * total_height / count)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{height_px}" '
        f'viewBox="0 0 {count} {total_height}" shape-rendering="crispEdges">',
        f'<rect width="{count}" height="{total_height}" fill="#fff"/>',
        f'<path d="{"".join(segments)}" fill="#000"/>',
    ]
    if caption:
        line_height = caption_height / 2
        for index, line in enumerate(caption_lines(qr)):
            parts.append(
                _svg_text(
                    line,
                    x=count / 2,
                    y=count + (index + 0.5) * line_height,
                    font_size=line_height * 0.55,
                    max_width=count - 2 * BORDER_MODULES,
                )
            )
    parts.append("</svg>")
    return "\n".join(parts)


SVG_MAX_CHARS = 60


def _svg_text(line: str, *, x: float, y: float, font_size: float, max_width: float) -> str:
    """Texte centré ; une ligne longue est tronquée puis comprimée pour tenir dans la largeur du QR."""
    if len(line) > SVG_MAX_CHARS:
        line = f"{line[: SVG_MAX_CHARS - 1].rstrip()}…"
    attributes = (
        f'x="{round(x, 2)}" y="{round(y, 2)}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{round(font_size, 2)}" text-anchor="middle" dominant-baseline="middle"'
    )
    if len(line) > 40:
        attributes += f' textLength="{round(max_width, 2)}" lengthAdjust="spacingAndGlyphs"'
    return f"<text {attributes}>{escape(line)}</text>"


def render(qr: QRCode, *, fmt: str, size: int = DEFAULT_SIZE, caption: bool = False) -> tuple[bytes, str]:
    """(contenu, type MIME) après vérification que le QR peut être imprimé."""
    ensure_printable(qr)
    if fmt == "svg":
        return render_svg(qr, size=size, caption=caption).encode("utf-8"), FORMATS["svg"]
    return render_png(qr, size=size, caption=caption), FORMATS["png"]
