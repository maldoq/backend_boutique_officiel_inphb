"""Lectures des boxes et QR pour l'administration.

Les scans sont comptés par la relation inverse « tracking_events » (nom de relation, sans importer
`tracking`, qui vient après `boxes` dans l'ordre des dépendances C.2).
"""

from django.db.models import Count, Max, Prefetch, Q, QuerySet

from .models import Box, QRCode

SCANS = Q(tracking_events__event_type="qr_scan")
CHAIN_LIMIT = 50


def admin_qr_queryset() -> QuerySet[QRCode]:
    return (
        QRCode.objects.select_related("box", "product", "replaced_by", "created_by")
        .annotate(
            scans_count=Count("tracking_events", filter=SCANS),
            last_scanned_at=Max("tracking_events__occurred_at", filter=SCANS),
        )
        .order_by("-created_at", "-id")
    )


def admin_box_queryset() -> QuerySet[Box]:
    active_qrs = QRCode.objects.filter(is_active=True).select_related("product").order_by("product__name")
    return (
        Box.objects.annotate(
            active_qr_count=Count("qr_codes", filter=Q(qr_codes__is_active=True), distinct=True),
            qr_count=Count("qr_codes", distinct=True),
            scans_count=Count("tracking_events", filter=SCANS, distinct=True),
        )
        .prefetch_related(Prefetch("qr_codes", queryset=active_qrs, to_attr="active_qrs"))
        .order_by("site", "code")
    )


def qr_chain(qr: QRCode) -> tuple[list[QRCode], list[QRCode]]:
    """(prédécesseurs du plus ancien au plus récent, successeurs du plus proche au plus récent)."""
    predecessors, current = [], qr
    while len(predecessors) < CHAIN_LIMIT:
        previous = QRCode.objects.filter(replaced_by=current).first()
        if previous is None:
            break
        predecessors.insert(0, previous)
        current = previous
    successors, current = [], qr
    while current.replaced_by_id and len(successors) < CHAIN_LIMIT:
        current = QRCode.objects.get(pk=current.replaced_by_id)
        successors.append(current)
    return predecessors, successors
