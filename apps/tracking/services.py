"""Traçabilité : résolution d'un QR scanné (étape 9) ; autres événements à l'étape 11.

La résolution vit ici et non dans `boxes` : elle écrit un événement, et `tracking` dépend de
`boxes` (C.2), jamais l'inverse.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from apps.boxes.models import QRCode, normalize_qr_code
from apps.catalog.selectors import visible_products
from apps.core.exceptions import GoneError, NotFoundError

from .choices import EventType
from .models import TrackingEvent


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
