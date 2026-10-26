import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.core.models import SiteSettings
from apps.inventory.choices import StockReason
from apps.inventory.models import StockMovement, StockMovementImmutableError
from apps.inventory.selectors import low_stock_variants, out_of_stock_variants, stock_drift
from apps.inventory.services import apply_movement

pytestmark = pytest.mark.django_db


def restock(variant, quantity):
    with transaction.atomic():
        return apply_movement(variant=variant, delta=quantity, reason=StockReason.RESTOCK)


# --- Historique inaltérable -------------------------------------------------------------


def test_mouvement_inalterable():
    movement = restock(VariantFactory(stock_quantity=0), 5)
    movement.note = "falsifié"
    with pytest.raises(StockMovementImmutableError):
        movement.save()
    with pytest.raises(StockMovementImmutableError):
        movement.delete()
    with pytest.raises(StockMovementImmutableError):
        StockMovement.objects.update(note="falsifié")
    with pytest.raises(StockMovementImmutableError):
        StockMovement.objects.all().delete()
    with pytest.raises(StockMovementImmutableError):
        StockMovement.objects.bulk_update([movement], ["note"])


def test_contraintes_en_base():
    variant = VariantFactory()
    for kwargs in ({"delta": 0, "balance_after": 1}, {"delta": 1, "balance_after": -1}):
        with pytest.raises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(variant=variant, reason=StockReason.RESTOCK, **kwargs)


def test_variante_avec_historique_non_supprimable():
    variant = VariantFactory(stock_quantity=0)
    restock(variant, 5)
    with pytest.raises(ProtectedError):
        variant.delete()


# --- Alertes de stock ------------------------------------------------------------------


def test_alertes_stock_faible_et_rupture():
    site = SiteSettings.load()
    site.default_low_stock_threshold = 3
    site.save()
    product = ProductFactory(variants=False, name="Polo")
    out = VariantFactory(product=product, size="XL", stock_quantity=0)
    low = VariantFactory(product=product, size="M", stock_quantity=3)
    own_threshold = VariantFactory(product=product, size="L", stock_quantity=8, low_stock_threshold=10)
    VariantFactory(product=product, size="S", stock_quantity=4)  # > 3 : pas d'alerte
    VariantFactory(product=product, size="XXL", stock_quantity=0, is_active=False)  # inactive : ignorée
    VariantFactory(product__is_active=False, stock_quantity=0)  # produit inactif : ignoré
    coming = VariantFactory(product__is_coming_soon=True, stock_quantity=0)

    assert list(low_stock_variants()) == [low, own_threshold]
    assert set(out_of_stock_variants()) == {out, coming}
    assert next(v for v in out_of_stock_variants() if v.pk == coming.pk).product.is_coming_soon


def test_alertes_sans_requete_par_variante(django_assert_num_queries):
    SiteSettings.load()
    for size in ("S", "M", "L", "XL", "XXL"):
        VariantFactory(size=size, stock_quantity=1)
    with django_assert_num_queries(2):  # paramètres + alertes (produit et catégorie joints)
        rows = [(v.product.name, v.product.category.name) for v in low_stock_variants()]
    assert len(rows) == 5


# --- Contrôle de cohérence ----------------------------------------------------------------


def test_check_stock_coherent(capsys):
    variant = VariantFactory(stock_quantity=0)
    restock(variant, 5)
    VariantFactory(stock_quantity=0)  # aucun mouvement, stock 0 : cohérent
    call_command("check_stock")
    assert "aucun écart" in capsys.readouterr().out


def test_check_stock_detecte_une_modification_hors_service(capsys):
    variant = VariantFactory(stock_quantity=0, size="M")
    restock(variant, 5)
    ProductVariant.objects.filter(pk=variant.pk).update(stock_quantity=9)  # contournement du service
    assert list(stock_drift()) == [variant]
    with pytest.raises(CommandError):
        call_command("check_stock")
    assert variant.sku in capsys.readouterr().err
