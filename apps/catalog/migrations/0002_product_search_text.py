from django.db import migrations, models

from apps.core.text import normalize_search


def fill_search_text(apps, schema_editor):
    """Remplit le texte de recherche des produits déjà existants."""
    Product = apps.get_model("catalog", "Product")
    ProductVariant = apps.get_model("catalog", "ProductVariant")
    for product in Product.objects.all().iterator():
        skus = ProductVariant.objects.filter(product_id=product.pk).values_list("sku", flat=True)
        text = " ".join([product.name, product.reference, product.short_description, *skus])
        Product.objects.filter(pk=product.pk).update(search_text=normalize_search(text))


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="search_text",
            field=models.TextField(blank=True, editable=False, verbose_name="texte de recherche"),
        ),
        migrations.RunPython(fill_search_text, migrations.RunPython.noop),
    ]
