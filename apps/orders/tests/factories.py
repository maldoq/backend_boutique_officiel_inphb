"""Fabriques de commandes cohérentes (montants et attribution respectent les contraintes en base)."""

import uuid

import factory

from apps.core.codes import random_code
from apps.orders.models import Order, OrderItem, PickupPoint


class PickupPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PickupPoint

    code = factory.Sequence(lambda n: f"POINT-TEST-{n:02d}")
    name = factory.Sequence(lambda n: f"Point de retrait de test {n}")


class OrderFactory(factory.django.DjangoModelFactory):
    """Commande sans ligne (montants à 0) ; utiliser make_order() pour des lignes et des totaux."""

    class Meta:
        model = Order

    public_reference = factory.LazyFunction(lambda: f"CMD-{random_code(8)}")
    pickup_code = factory.LazyFunction(lambda: random_code(6))
    customer_first_name = "Awa"
    customer_last_name = "Koné"
    customer_phone = "+2250700000000"
    pickup_point = factory.SubFactory(PickupPointFactory)
    channel = "web"
    visitor_id = factory.LazyFunction(uuid.uuid4)


def make_order(lines, **fields) -> Order:
    """lines : [(variant, quantité, qr | None)] ; prix, instantanés et totaux calculés comme le serveur."""
    order = OrderFactory(**fields)
    subtotal = 0
    for variant, quantity, qr in lines:
        unit = variant.effective_price_xof
        OrderItem.objects.create(
            order=order,
            variant=variant,
            product=variant.product,
            product_name=variant.product.name,
            product_reference=variant.product.reference,
            variant_label=variant.label,
            sku=variant.sku,
            unit_price_xof=unit,
            quantity=quantity,
            line_total_xof=unit * quantity,
            source_qr=qr,
            source_box=qr.box if qr else None,
            source_product=qr.product if qr else None,
        )
        subtotal += unit * quantity
    Order.objects.filter(pk=order.pk).update(subtotal_xof=subtotal, total_xof=subtotal)
    order.refresh_from_db()
    return order
