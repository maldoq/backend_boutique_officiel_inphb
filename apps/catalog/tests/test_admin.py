"""Django Admin du catalogue : création avec variantes et photos, stock en lecture seule, audit."""

import pytest

from apps.audit.models import AuditLog
from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.catalog.tests.factories import (
    CategoryFactory,
    ProductFactory,
    ProductImageFactory,
    make_image_file,
)

pytestmark = pytest.mark.django_db

ADD_URL = "/django-admin/catalog/product/add/"


@pytest.fixture
def staff_client(client, make_staff):
    admin = make_staff(email="root@exemple.ci", is_superuser=True)
    client.force_login(admin)
    client.admin = admin
    return client


def _errors(response):
    """Erreurs du formulaire principal et des inlines (message d'échec lisible)."""
    if not response.context:
        return ""
    found = {"form": response.context["adminform"].form.errors}
    for inline in response.context["inline_admin_formsets"]:
        found[inline.formset.prefix] = [inline.formset.non_form_errors(), inline.formset.errors]
    return found


def management(prefix, total, initial=0):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


def product_data(category, **overrides):
    data = {
        "reference": "inp-tex-001",
        "name": "Polo INP-HB Vert",
        "slug": "",
        "category": category.pk,
        "short_description": "Polo brodé. Produit de démonstration.",
        "description": "",
        "price_xof": "12000",
        "compare_at_price_xof": "15000",
        "is_active": "on",
        "seo_title": "",
        "seo_description": "",
        **management("variants", 0),
        **management("images", 0),
    }
    data.update(overrides)
    return data


def variant_fields(index, **fields):
    base = {
        "size": "",
        "color": "",
        "model": "",
        "sku": "",
        "price_xof": "",
        "low_stock_threshold": "",
        "is_active": "on",
        "position": "0",
    }
    base.update(fields)
    return {f"variants-{index}-{name}": value for name, value in base.items()}


def test_creation_produit_avec_variantes_et_photo(staff_client):
    category = CategoryFactory(name="Textile")
    data = product_data(
        category,
        **management("variants", 2),
        **variant_fields(0, size="M", color="Vert", stock_quantity="99"),
        **variant_fields(1, size="L", color="Vert", position="1"),
        **management("images", 1),
        **{"images-0-image": make_image_file(), "images-0-alt_text": "Polo vert", "images-0-position": "0"},
    )
    response = staff_client.post(ADD_URL, data)
    assert response.status_code == 302, _errors(response)

    product = Product.objects.get()
    assert product.reference == "INP-TEX-001"
    assert product.slug == "polo-inp-hb-vert"
    assert product.created_by == staff_client.admin
    variants = list(product.variants.order_by("position"))
    assert [(v.label, v.sku) for v in variants] == [
        ("M / Vert", "INP-TEX-001-M-VERT"),
        ("L / Vert", "INP-TEX-001-L-VERT"),
    ]
    assert all(v.stock_quantity == 0 for v in variants)  # stock en lecture seule : 99 ignoré
    image = ProductImage.objects.get()
    assert image.is_main and image.thumbnail

    assert AuditLog.objects.filter(action="product.create", object_id=str(product.pk)).count() == 1
    assert AuditLog.objects.filter(action="variant.create").count() == 2


def test_changer_l_image_principale_dans_l_admin(staff_client):
    product = ProductFactory()
    first = ProductImageFactory(product=product, position=0)
    second = ProductImageFactory(product=product, position=1)
    variant = product.variants.get()
    data = product_data(
        product.category,
        reference=product.reference,
        name=product.name,
        slug=product.slug,
        compare_at_price_xof="",
        **management("variants", 1, initial=1),
        **variant_fields(0, id=str(variant.pk), product=str(product.pk)),
        **management("images", 2, initial=2),
    )
    for index, image in enumerate((first, second)):
        data.update(
            {
                f"images-{index}-id": str(image.pk),
                f"images-{index}-product": str(product.pk),
                f"images-{index}-alt_text": "",
                f"images-{index}-position": str(index),
            }
        )
    data["images-1-is_main"] = "on"  # la seconde devient principale
    response = staff_client.post(f"/django-admin/catalog/product/{product.pk}/change/", data)
    assert response.status_code == 302, _errors(response)
    first.refresh_from_db()
    second.refresh_from_db()
    assert second.is_main and not first.is_main


def test_variante_standard_creee_sans_rien_saisir(staff_client):
    data = product_data(CategoryFactory(), **management("variants", 1), **variant_fields(0))
    assert staff_client.post(ADD_URL, data).status_code == 302
    variant = ProductVariant.objects.get()
    assert (variant.label, variant.sku) == ("Standard", "INP-TEX-001")


def test_produit_sans_variante_refuse(staff_client):
    response = staff_client.post(ADD_URL, product_data(CategoryFactory()))
    assert response.status_code == 200
    assert not Product.objects.exists()


def test_prix_barre_incoherent_refuse(staff_client):
    data = product_data(
        CategoryFactory(), compare_at_price_xof="9000", **management("variants", 1), **variant_fields(0)
    )
    response = staff_client.post(ADD_URL, data)
    assert response.status_code == 200
    assert "compare_at_price_xof" in response.context["adminform"].form.errors


def _change_data(product, **overrides):
    variant = product.variants.get()
    data = product_data(
        product.category,
        reference=product.reference,
        name=product.name,
        slug=product.slug,
        compare_at_price_xof="",
        **management("variants", 1, initial=1),
        **variant_fields(0, id=str(variant.pk), product=str(product.pk)),
    )
    data.update(overrides)
    return data


def test_changement_de_prix_audite(staff_client):
    product = ProductFactory(price_xof=12000)
    response = staff_client.post(
        f"/django-admin/catalog/product/{product.pk}/change/",
        _change_data(product, price_xof="13500", name="Polo INP-HB Vert foncé"),
    )
    assert response.status_code == 302
    price = AuditLog.objects.get(action="product.price_change")
    assert price.changes == {"price_xof": [12000, 13500]}
    assert AuditLog.objects.get(action="product.update").changes["name"][1] == "Polo INP-HB Vert foncé"


def test_prix_de_variante_audite(staff_client):
    product = ProductFactory()
    variant = product.variants.get()
    data = _change_data(product)
    data["variants-0-price_xof"] = "14000"
    assert staff_client.post(f"/django-admin/catalog/product/{product.pk}/change/", data).status_code == 302
    entry = AuditLog.objects.get(action="variant.price_change")
    assert entry.object_id == str(variant.pk)
    assert entry.changes == {"price_xof": [None, 14000]}


def test_suppression_desactivee_au_profit_de_la_desactivation(staff_client):
    product = ProductFactory()
    assert staff_client.get(f"/django-admin/catalog/product/{product.pk}/delete/").status_code == 403
    response = staff_client.post(
        "/django-admin/catalog/product/",
        {"action": "deactivate_products", "_selected_action": [product.pk]},
    )
    assert response.status_code == 302
    product.refresh_from_db()
    assert product.is_active is False
    assert AuditLog.objects.get(action="product.update").changes == {"is_active": [True, False]}


def test_pages_admin_du_catalogue(staff_client):
    product = ProductFactory()
    for url in (
        "/django-admin/catalog/product/",
        ADD_URL,
        f"/django-admin/catalog/product/{product.pk}/change/",
        "/django-admin/catalog/category/",
        "/django-admin/catalog/category/add/",
    ):
        assert staff_client.get(url).status_code == 200, url


def test_seules_les_categories_racines_peuvent_etre_parentes(staff_client):
    textile = Category.objects.create(name="Textile")
    Category.objects.create(name="Polos", parent=textile)
    response = staff_client.get("/django-admin/catalog/category/add/")
    choices = list(response.context["adminform"].form.fields["parent"].queryset)
    assert choices == [textile]


def test_categorie_utilisee_non_supprimee(staff_client):
    product = ProductFactory()
    staff_client.post(f"/django-admin/catalog/category/{product.category.pk}/delete/", {"post": "yes"})
    assert Category.objects.filter(pk=product.category.pk).exists()
