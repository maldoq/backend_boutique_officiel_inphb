from io import BytesIO

import factory
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.models import Category, Product, ProductImage, ProductVariant


def make_image_file(name="photo.jpg", size=(1200, 900), fmt="JPEG", color=(6, 113, 56), exif=None):
    buffer = BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, color=color).save(buffer, format=fmt, **kwargs)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Catégorie {n}")


class ProductFactory(factory.django.DjangoModelFactory):
    """Produit actif avec une variante « Standard » (stock 20) ; variants=False : aucune variante."""

    class Meta:
        model = Product
        skip_postgeneration_save = True

    reference = factory.Sequence(lambda n: f"INP-TST-{n:03d}")
    name = factory.Sequence(lambda n: f"Produit de démonstration {n}")
    category = factory.SubFactory(CategoryFactory)
    short_description = "Produit de démonstration."
    price_xof = 12000

    @factory.post_generation
    def variants(self, create, extracted, **kwargs):
        if create and extracted is not False:
            VariantFactory(product=self, stock_quantity=kwargs.get("stock", 20))


class VariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory, variants=False)
    stock_quantity = 20


class ProductImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductImage

    product = factory.SubFactory(ProductFactory)
    image = factory.LazyFunction(make_image_file)
    alt_text = "Photo de démonstration"
