import pytest
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.catalog.models import ProductVariant
from apps.catalog.tests.factories import VariantFactory
from apps.core.exceptions import ConflictError, InsufficientStock, NotFoundError
from apps.inventory.choices import StockReason
from apps.inventory.models import StockMovement
from apps.inventory.services import (
    MAX_STOCK,
    StockLimitExceeded,
    adjust_stock,
    apply_movement,
    set_initial_stock,
)

pytestmark = pytest.mark.django_db


def stock_of(variant) -> int:
    return ProductVariant.objects.get(pk=variant.pk).stock_quantity


def move(variant, delta, reason=StockReason.MANUAL_ADJUSTMENT, **kwargs):
    with transaction.atomic():
        return apply_movement(variant=variant, delta=delta, reason=reason, **kwargs)


# --- apply_movement ------------------------------------------------------------------


def test_entree_et_sortie_historisees(make_staff):
    variant = VariantFactory(stock_quantity=5)
    agent = make_staff()
    entry = move(variant, 7, StockReason.RESTOCK, user=agent, note="Livraison atelier")
    exit_ = move(variant, -3)
    assert stock_of(variant) == 9
    assert (entry.delta, entry.balance_after, entry.created_by, entry.note) == (
        7,
        12,
        agent,
        "Livraison atelier",
    )
    assert (exit_.delta, exit_.balance_after, exit_.created_by) == (-3, 9, None)
    assert variant.stock_quantity == 9  # instance tenue à jour


def test_sortie_superieure_au_stock_refusee_sans_effet():
    variant = VariantFactory(stock_quantity=2)
    with pytest.raises(InsufficientStock) as info:
        move(variant, -3, StockReason.ORDER_RESERVED)
    assert info.value.details == {"items": [{"variant_id": variant.pk, "requested": 3, "available": 2}]}
    assert "Stock insuffisant" in info.value.message
    assert stock_of(variant) == 2
    assert not StockMovement.objects.exists()


def test_sortie_de_tout_le_stock_autorisee():
    variant = VariantFactory(stock_quantity=2)
    assert move(variant, -2, StockReason.ORDER_RESERVED).balance_after == 0


def test_plafond_de_stock():
    variant = VariantFactory(stock_quantity=MAX_STOCK - 1)
    with pytest.raises(StockLimitExceeded):
        move(variant, 2, StockReason.RESTOCK)
    assert stock_of(variant) == MAX_STOCK - 1


@pytest.mark.django_db(transaction=True)  # sans la transaction englobante habituelle des tests
def test_transaction_obligatoire():
    variant = VariantFactory(stock_quantity=1)
    with pytest.raises(RuntimeError):
        apply_movement(variant=variant, delta=1, reason=StockReason.RESTOCK)
    assert stock_of(variant) == 1


@pytest.mark.parametrize(
    ("delta", "reason"),
    [
        (0, StockReason.RESTOCK),
        (-1, StockReason.RESTOCK),
        (-1, StockReason.RETURN),
        (-1, StockReason.INITIAL),
        (-1, StockReason.ORDER_CANCELLED),
        (1, StockReason.ORDER_RESERVED),
        (1, "inconnu"),
    ],
)
def test_sens_et_motif_incoherents_refuses(delta, reason):
    variant = VariantFactory(stock_quantity=5)
    with pytest.raises(ValueError):
        move(variant, delta, reason)
    assert stock_of(variant) == 5


def test_stock_reel_utilise_meme_si_l_instance_est_perimee():
    """Une instance chargée avant une autre écriture ne peut pas écraser le stock (pas de « lost update »)."""
    variant = VariantFactory(stock_quantity=5)
    stale = ProductVariant.objects.get(pk=variant.pk)
    move(variant, -4, StockReason.ORDER_RESERVED)  # stock réel : 1
    with pytest.raises(InsufficientStock):
        move(stale, -2, StockReason.ORDER_RESERVED)  # l'instance croit qu'il en reste 5
    assert move(stale, -1, StockReason.ORDER_RESERVED).balance_after == 0


# --- adjust_stock ---------------------------------------------------------------------


def test_ajustement_par_nouvelle_quantite_audite(make_staff):
    variant = VariantFactory(stock_quantity=10)
    agent = make_staff("GESTIONNAIRE_CATALOGUE")
    movement = adjust_stock(variant_id=variant.pk, user=agent, new_quantity=25, reason=StockReason.RESTOCK)
    assert (movement.delta, movement.balance_after) == (15, 25)
    assert stock_of(variant) == 25
    entry = AuditLog.objects.get(action="stock.adjust")
    assert entry.actor == agent
    assert entry.object_id == str(variant.pk)
    assert entry.changes == {"stock_quantity": [10, 25], "reason": [None, "restock"], "note": [None, ""]}


def test_ajustement_par_variation_avec_note(make_staff):
    variant = VariantFactory(stock_quantity=10)
    movement = adjust_stock(
        variant_id=variant.pk,
        user=make_staff(),
        delta=-2,
        reason=StockReason.MANUAL_ADJUSTMENT,
        note="  2 polos tachés  ",
    )
    assert (movement.balance_after, movement.note) == (8, "2 polos tachés")


def test_ajustement_sous_zero_refuse_et_non_audite(make_staff):
    variant = VariantFactory(stock_quantity=1)
    with pytest.raises(InsufficientStock):
        adjust_stock(
            variant_id=variant.pk,
            user=make_staff(),
            delta=-2,
            reason=StockReason.INVENTORY_CORRECTION,
            note="Inventaire",
        )
    assert stock_of(variant) == 1
    assert not AuditLog.objects.exists() and not StockMovement.objects.exists()


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"new_quantity": 10, "reason": StockReason.RESTOCK}, "new_quantity"),  # déjà 10
        ({"new_quantity": 12, "delta": 2, "reason": StockReason.RESTOCK}, "non_field_errors"),
        ({"reason": StockReason.RESTOCK}, "non_field_errors"),
        ({"new_quantity": -1, "reason": StockReason.RESTOCK}, "new_quantity"),
        ({"delta": 0, "reason": StockReason.RESTOCK}, "delta"),
        ({"delta": 5, "reason": StockReason.ORDER_RESERVED}, "reason"),  # réservé au système
        ({"delta": 5, "reason": StockReason.INITIAL}, "reason"),
        ({"delta": -2, "reason": StockReason.RESTOCK}, "reason"),  # un réassort augmente
        ({"new_quantity": 4, "reason": StockReason.RETURN}, "reason"),  # un retour augmente
        ({"delta": -2, "reason": StockReason.MANUAL_ADJUSTMENT}, "note"),  # note obligatoire
        ({"delta": -2, "reason": StockReason.INVENTORY_CORRECTION, "note": "   "}, "note"),
        ({"delta": 1, "reason": StockReason.RESTOCK, "note": "x" * 256}, "note"),
    ],
)
def test_ajustement_invalide(make_staff, kwargs, field):
    variant = VariantFactory(stock_quantity=10)
    with pytest.raises(ValidationError) as info:
        adjust_stock(variant_id=variant.pk, user=make_staff(), **kwargs)
    assert field in info.value.detail
    assert stock_of(variant) == 10


def test_ajustement_variante_inconnue(make_staff):
    with pytest.raises(NotFoundError):
        adjust_stock(variant_id=999999, user=make_staff(), delta=1, reason=StockReason.RESTOCK)


# --- set_initial_stock ----------------------------------------------------------------


def test_stock_initial(make_staff):
    variant = VariantFactory(stock_quantity=0)
    movement = set_initial_stock(variant=variant, quantity=30, user=make_staff())
    assert (movement.reason, movement.delta, movement.balance_after) == ("initial", 30, 30)
    assert AuditLog.objects.get(action="stock.initial").changes == {"stock_quantity": [0, 30]}


def test_stock_initial_nul_ou_deja_initialise():
    variant = VariantFactory(stock_quantity=0)
    assert set_initial_stock(variant=variant, quantity=0) is None
    set_initial_stock(variant=variant, quantity=5)
    with pytest.raises(ConflictError) as info:
        set_initial_stock(variant=variant, quantity=5)
    assert info.value.code == "stock_already_initialized"
    with pytest.raises(ConflictError):
        set_initial_stock(variant=VariantFactory(stock_quantity=3), quantity=5)  # stock hérité sans mouvement
