from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.tracking.models import TrackingEvent


class Command(BaseCommand):
    help = (
        "Supprime les événements de traçabilité plus anciens que TRACKING_RETENTION_DAYS (730 j par défaut). "
        "À planifier une fois par jour en production."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Durée de conservation (jours).")
        parser.add_argument("--batch-size", type=int, default=5000, help="Suppression par lots de N lignes.")
        parser.add_argument("--dry-run", action="store_true", help="Compte sans supprimer.")

    def handle(self, *args, days=None, batch_size=5000, dry_run=False, **options):
        days = settings.TRACKING_RETENTION_DAYS if days is None else days
        if days < 1:
            raise CommandError("La durée de conservation doit être d'au moins 1 jour.")
        if batch_size < 1:
            raise CommandError("--batch-size doit être positif.")
        cutoff = timezone.now() - timedelta(days=days)
        expired = TrackingEvent.objects.filter(occurred_at__lt=cutoff)
        if dry_run:
            self.stdout.write(
                f"{expired.count()} événement(s) antérieur(s) au {cutoff:%Y-%m-%d} seraient supprimés."
            )
            return
        deleted = 0
        while True:  # par lots : pas de transaction géante sur des millions de lignes
            ids = list(expired.order_by("id").values_list("id", flat=True)[:batch_size])
            if not ids:
                break
            deleted += TrackingEvent.objects.filter(id__in=ids).delete()[0]
        message = f"{deleted} événement(s) antérieur(s) au {cutoff:%Y-%m-%d} supprimé(s)"
        self.stdout.write(self.style.SUCCESS(f"{message} (conservation : {days} j)."))
