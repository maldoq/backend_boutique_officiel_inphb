from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.accounts.capabilities import ROLES


class Command(BaseCommand):
    help = "Crée les 6 groupes de rôles du personnel (idempotent : relançable sans risque)."

    def handle(self, *args, **options):
        for code, role in ROLES.items():
            _, created = Group.objects.get_or_create(name=code)
            state = "créé" if created else "déjà présent"
            self.stdout.write(
                f"  {code:<24} {state:<13} {len(role.capabilities):>2} capacités — {role.label}"
            )
        self.stdout.write(self.style.SUCCESS(f"{len(ROLES)} rôles prêts."))
