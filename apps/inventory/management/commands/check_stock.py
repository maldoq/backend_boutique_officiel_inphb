from django.core.management.base import BaseCommand, CommandError

from apps.inventory.selectors import stock_drift


class Command(BaseCommand):
    help = (
        "Vérifie que le stock de chaque variante est égal à la somme de ses mouvements. "
        "Un écart signale une modification faite hors des services de stock."
    )

    def handle(self, *args, **options):
        drifts = list(stock_drift())
        if not drifts:
            self.stdout.write(
                self.style.SUCCESS("Stock cohérent : aucun écart avec l'historique des mouvements.")
            )
            return
        for variant in drifts:
            self.stderr.write(
                f"  {variant.sku:<30} stock affiché {variant.stock_quantity:>6} "
                f"≠ somme des mouvements {variant.movements_total:>6}  ({variant})"
            )
        raise CommandError(
            f"{len(drifts)} variante(s) incohérente(s). Corriger par un ajustement d'inventaire."
        )
