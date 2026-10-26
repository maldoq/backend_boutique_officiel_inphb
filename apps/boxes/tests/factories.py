import factory
from django.utils import timezone

from apps.boxes.models import Box, QRCode
from apps.catalog.tests.factories import ProductFactory
from apps.core.codes import random_code


class BoxFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Box

    code = factory.Sequence(lambda n: f"BOX-TEST-{n:02d}")
    label = factory.Sequence(lambda n: f"Box de test {n}")
    site = "Centre"


class QRCodeFactory(factory.django.DjangoModelFactory):
    """QR actif (créé directement : les règles métier sont testées via les services)."""

    class Meta:
        model = QRCode

    code = factory.LazyFunction(lambda: random_code(10))
    box = factory.SubFactory(BoxFactory)
    product = factory.SubFactory(ProductFactory)
    activated_at = factory.LazyFunction(timezone.now)
