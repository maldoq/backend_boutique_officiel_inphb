"""Traçabilité : résolution d'un QR scanné (étape 9) et événements du tunnel (étape 11).

La résolution vit ici et non dans `boxes` : elle écrit un événement, et `tracking` dépend de
`boxes` (C.2), jamais l'inverse.

Attribution (R06) : jamais à partir d'un box_code. Un source_qr_code ne suffit pas non plus (les codes
sont imprimés en vitrine, donc publics) : avec ATTRIBUTION_REQUIRES_SCAN, il faut que CE visiteur ait
réellement scanné CE QR (événement qr_scan écrit par le serveur) dans la fenêtre ATTRIBUTION_WINDOW_DAYS.
La box et le produit retenus sont ceux du scan : une réaffectation ultérieure du QR ne déplace pas
l'attribution.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.boxes.models import Box, QRCode, normalize_qr_code
from apps.catalog.models import Product, ProductVariant
from apps.catalog.selectors import visible_products
from apps.core.exceptions import GoneError, NotFoundError
from apps.core.request_context import is_app_version

from .choices import CLIENT_EVENTS, DEDUPLICATED_EVENTS, EventType
from .models import TrackingEvent

_SCREEN = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
METADATA_MAX_BYTES = 1024


@dataclass(frozen=True)
class QrResolution:
    qr: QRCode
    scanned_at: datetime
    recorded: bool  # False : même visiteur, même QR, dans la fenêtre anti-doublon


def resolve_qr(*, code: str, visitor_id: UUID, channel: str) -> QrResolution:
    """Valide un QR, enregistre le scan (horodatage serveur, R07) et renvoie box et produit (R06)."""
    normalized = normalize_qr_code(code)
    qr = (
        QRCode.objects.select_related("box", "product").filter(code=normalized).first()
        if normalized
        else None
    )
    if qr is None:
        raise NotFoundError("Ce QR code est inconnu.", code="qr_not_found")
    # Même règle de visibilité que le catalogue public : jamais de redirection vers une fiche 404.
    if not (qr.is_active and qr.box.is_active and visible_products().filter(pk=qr.product_id).exists()):
        raise GoneError("Ce QR code n'est plus actif.", code="qr_inactive", details={"redirect_path": "/"})

    window_start = timezone.now() - timedelta(seconds=settings.QR_SCAN_DEDUP_SECONDS)
    previous = (
        TrackingEvent.objects.filter(
            event_type=EventType.QR_SCAN, qr=qr, visitor_id=visitor_id, occurred_at__gte=window_start
        )
        .order_by("-occurred_at")
        .first()
    )
    if previous is not None:  # un rafraîchissement de page n'est pas un nouveau scan
        return QrResolution(qr=qr, scanned_at=previous.occurred_at, recorded=False)
    event = TrackingEvent.objects.create(
        event_type=EventType.QR_SCAN,
        visitor_id=visitor_id,
        channel=channel,
        qr=qr,
        box=qr.box,
        product=qr.product,
    )
    return QrResolution(qr=qr, scanned_at=event.occurred_at, recorded=True)


# --- Événements du tunnel ----------------------------------------------------------------


@dataclass(frozen=True)
class Attribution:
    qr: QRCode
    box: Box | None


@dataclass(frozen=True)
class RecordedEvent:
    event: TrackingEvent
    recorded: bool  # False : doublon dans la fenêtre anti-doublon, l'événement existant est renvoyé
    attribution_applied: bool


def find_attribution(
    *, source_qr_code: str | None, product: Product | None, visitor_id: UUID
) -> Attribution | None:
    """Attribution déduite du code QR par le serveur (R06) ; None si rien n'est prouvable."""
    code = normalize_qr_code(source_qr_code or "")
    if not code or product is None:
        return None
    qr = QRCode.objects.filter(code=code).first()
    if qr is None:
        return None
    if not settings.ATTRIBUTION_REQUIRES_SCAN:
        return Attribution(qr=qr, box=qr.box) if qr.product_id == product.pk else None
    since = timezone.now() - timedelta(days=settings.ATTRIBUTION_WINDOW_DAYS)
    scan = (
        TrackingEvent.objects.filter(
            event_type=EventType.QR_SCAN, qr=qr, visitor_id=visitor_id, occurred_at__gte=since
        )
        .select_related("box")
        .order_by("-occurred_at")
        .first()
    )
    # Le produit et la box retenus sont ceux du scan (un QR désactivé ou réaffecté depuis reste valable).
    if scan is None or scan.product_id != product.pk:
        return None
    return Attribution(qr=qr, box=scan.box)


def clean_metadata(raw, *, app_version: str | None = None) -> dict:
    """Liste blanche (R08) : client_timestamp (date ISO), app_version, screen (identifiant d'écran).

    Toute autre clé, ou toute valeur invalide, est supprimée : pas de texte libre (risque de donnée
    personnelle). L'heure du client est indicative : occurred_at reste l'heure du serveur (R07).
    """
    raw = raw if isinstance(raw, dict) else {}
    cleaned = {}
    timestamp = raw.get("client_timestamp")
    if isinstance(timestamp, str) and len(timestamp) <= 40 and parse_datetime(timestamp) is not None:
        cleaned["client_timestamp"] = timestamp
    version = raw.get("app_version") or app_version
    if is_app_version(version):
        cleaned["app_version"] = version
    screen = raw.get("screen")
    if isinstance(screen, str) and _SCREEN.match(screen):
        cleaned["screen"] = screen
    return cleaned  # au plus ~120 octets : bien sous METADATA_MAX_BYTES


def record_event(
    *,
    event_type: str,
    visitor_id: UUID,
    channel: str,
    product: Product | None = None,
    variant: ProductVariant | None = None,
    source_qr_code: str | None = None,
    quantity: int | None = None,
    metadata=None,
    app_version: str | None = None,
) -> RecordedEvent:
    """Événement envoyé par le site ou l'application : horodatage serveur, aucune donnée personnelle."""
    if event_type not in CLIENT_EVENTS:
        raise ValueError(f"Type d'événement non autorisé depuis un client : {event_type!r}")
    if event_type in DEDUPLICATED_EVENTS:
        window_start = timezone.now() - timedelta(seconds=settings.TRACKING_DEDUP_SECONDS)
        previous = (
            TrackingEvent.objects.filter(
                event_type=event_type, visitor_id=visitor_id, product=product, occurred_at__gte=window_start
            )
            .order_by("-occurred_at")
            .first()
        )
        if previous is not None:
            return RecordedEvent(
                event=previous, recorded=False, attribution_applied=previous.qr_id is not None
            )
    attribution = find_attribution(source_qr_code=source_qr_code, product=product, visitor_id=visitor_id)
    event = TrackingEvent.objects.create(
        event_type=event_type,
        visitor_id=visitor_id,
        channel=channel,
        qr=attribution.qr if attribution else None,
        box=attribution.box if attribution else None,
        product=product,
        variant=variant,
        quantity=quantity,
        metadata=clean_metadata(metadata, app_version=app_version),
    )
    return RecordedEvent(event=event, recorded=True, attribution_applied=attribution is not None)
