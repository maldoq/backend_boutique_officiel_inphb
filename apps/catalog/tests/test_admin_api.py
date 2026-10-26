"""API d'administration du catalogue et du stock (étape 8)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.capabilities import ROLE_CAPABILITIES, ROLES
from apps.audit.models import AuditLog
from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.catalog.tests.factories import (
    CategoryFactory,
    ProductFactory,
    ProductImageFactory,
    VariantFactory,
    make_image_file,
)
from apps.core.models import SiteSettings
from apps.inventory.models import StockMovement

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/admin"


@pytest.fixture
def manager(admin_api_client):
    """Gestionnaire catalogue et stocks : catalog.* et stock.*."""
    return admin_api_client("GESTIONNAIRE_CATALOGUE")


def product_payload(category, **overrides):
    payload = {
        "reference": "inp tex 001",
        "name": "Polo INP-HB Vert",
        "category": category.pk,
        "short_description": "Polo brodé. Produit de démonstration.",
        "price_xof": 12000,
        "compare_at_price_xof": 15000,
        "variants": [
            {"size": "M", "color": "Vert", "initial_stock": 20},
            {"size": "XL", "color": "Vert", "price_xof": 14000},
        ],
    }
    payload.update(overrides)
    return payload


def error(response):
    return response.json()["error"]


# --- Permissions (matrice C.6) ------------------------------------------------------------

ROUTES = [
    ("get", "/categories/", "catalog.view"),
    ("post", "/categories/", "catalog.manage"),
    ("get", "/products/", "catalog.view"),
    ("post", "/products/", "catalog.manage"),
    ("get", "/products/{product}/", "catalog.view"),
    ("patch", "/products/{product}/", "catalog.manage"),
    ("delete", "/products/{product}/", "catalog.manage"),
    ("get", "/products/{product}/variants/", "catalog.view"),
    ("post", "/products/{product}/variants/", "catalog.manage"),
    ("post", "/products/{product}/images/", "catalog.manage"),
    ("post", "/products/{product}/images/reorder/", "catalog.manage"),
    ("get", "/variants/{variant}/", "catalog.view"),
    ("patch", "/variants/{variant}/", "catalog.manage"),
    ("delete", "/variants/{variant}/", "catalog.manage"),
    ("patch", "/product-images/{image}/", "catalog.manage"),
    ("delete", "/product-images/{image}/", "catalog.manage"),
    ("post", "/variants/{variant}/stock-adjustments/", "stock.manage"),
    ("get", "/stock/movements/", "stock.view"),
    ("get", "/stock/alerts/", "stock.view"),
]


def _url(template):
    product = ProductFactory()
    VariantFactory(product=product, size="M")
    ids = {
        "product": product.pk,
        "variant": product.variants.first().pk,
        "image": ProductImageFactory(product=product).pk,
    }
    return ADMIN + template.format(**ids)


@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize(("method", "template", "capability"), ROUTES)
def test_matrice_des_permissions(admin_api_client, role, method, template, capability):
    response = getattr(admin_api_client(role), method)(_url(template), {}, format="json")
    if capability in ROLE_CAPABILITIES[role]:
        assert response.status_code != 403, response.content
    else:
        assert response.status_code == 403
        assert error(response)["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "template", "capability"), ROUTES)
def test_anonyme_401(api_client, method, template, capability):
    assert getattr(api_client, method)(_url(template), {}, format="json").status_code == 401


def test_mot_de_passe_temporaire_bloque_le_catalogue(admin_api_client):
    client = admin_api_client("ADMIN_GENERAL", must_change_password=True)
    response = client.get(f"{ADMIN}/products/")
    assert response.status_code == 403 and error(response)["code"] == "password_change_required"


# --- Scénario T21 -----------------------------------------------------------------------


def test_T21_crud_produit_variante_stock_visible_au_public(manager, api_client):
    category = CategoryFactory(name="Textile")
    created = manager.post(f"{ADMIN}/products/", product_payload(category), format="json")
    assert created.status_code == 201, created.content
    data = created.json()
    product_id = data["id"]
    assert (data["reference"], data["slug"]) == ("INP-TEX-001", "polo-inp-hb-vert")
    assert data["created_by"] == manager.user.email
    variants = {v["label"]: v for v in data["variants"]}
    assert (
        variants["M / Vert"]["stock_quantity"] == 20 and variants["M / Vert"]["sku"] == "INP-TEX-001-M-VERT"
    )
    assert (
        variants["XL / Vert"]["stock_quantity"] == 0 and variants["XL / Vert"]["effective_price_xof"] == 14000
    )
    movement = StockMovement.objects.get()
    assert (movement.reason, movement.delta, movement.created_by) == ("initial", 20, manager.user)
    assert AuditLog.objects.filter(action="product.create").count() == 1
    assert AuditLog.objects.filter(action="variant.create").count() == 2

    assert [p["slug"] for p in api_client.get("/api/v1/products/").json()["results"]] == ["polo-inp-hb-vert"]

    patched = manager.patch(f"{ADMIN}/products/{product_id}/", {"price_xof": 13000}, format="json")
    assert patched.status_code == 200
    assert api_client.get("/api/v1/products/polo-inp-hb-vert/").json()["price_xof"] == 13000
    assert AuditLog.objects.get(action="product.price_change").changes == {"price_xof": [12000, 13000]}

    xl_id = variants["XL / Vert"]["id"]
    adjusted = manager.post(
        f"{ADMIN}/variants/{xl_id}/stock-adjustments/",
        {"new_quantity": 6, "reason": "restock"},
        format="json",
    )
    assert adjusted.status_code == 201, adjusted.content
    assert adjusted.json()["stock_quantity"] == 6
    public_variants = api_client.get("/api/v1/products/polo-inp-hb-vert/").json()["variants"]
    assert {v["label"]: v["availability"] for v in public_variants}["XL / Vert"] == "in_stock"

    manager.patch(f"{ADMIN}/products/{product_id}/", {"is_active": False}, format="json")
    assert api_client.get("/api/v1/products/").json()["count"] == 0
    assert api_client.get("/api/v1/products/polo-inp-hb-vert/").status_code == 404
    assert manager.get(f"{ADMIN}/products/{product_id}/").json()["is_active"] is False


# --- Création : validation et atomicité ------------------------------------------------------


def test_creation_atomique_si_une_variante_est_invalide(manager):
    payload = product_payload(
        CategoryFactory(),
        variants=[
            {"size": "M", "initial_stock": 5},
            {"size": "L", "sku": "SKU/INVALIDE"},
        ],
    )
    response = manager.post(f"{ADMIN}/products/", payload, format="json")
    assert response.status_code == 400
    assert "1" in error(response)["details"]["variants"]  # ligne en erreur identifiée
    assert not Product.objects.exists() and not ProductVariant.objects.exists()
    assert not StockMovement.objects.exists() and not AuditLog.objects.exists()


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"variants": []}, "variants"),
        ({"variants": [{"size": "M"}, {"size": " m "}]}, "variants"),  # même combinaison
        ({"compare_at_price_xof": 11000}, "compare_at_price_xof"),
        ({"price_xof": 0}, "price_xof"),
        ({"variants": [{"size": "M", "initial_stock": -1}]}, "variants"),
    ],
)
def test_creation_refusee(manager, overrides, field):
    response = manager.post(
        f"{ADMIN}/products/", product_payload(CategoryFactory(), **overrides), format="json"
    )
    assert response.status_code == 400
    assert error(response)["code"] == "validation_error"
    assert field in error(response)["details"]
    assert not Product.objects.exists()


def test_categorie_inactive_refusee(manager):
    response = manager.post(
        f"{ADMIN}/products/", product_payload(CategoryFactory(is_active=False)), format="json"
    )
    assert response.status_code == 400 and "category" in error(response)["details"]


def test_reference_en_double_insensible_a_la_casse(manager):
    ProductFactory(reference="INP-TEX-001")
    response = manager.post(f"{ADMIN}/products/", product_payload(CategoryFactory()), format="json")
    assert response.status_code == 400 and "reference" in error(response)["details"]


# --- Modification ----------------------------------------------------------------------


def test_produits_associes(manager):
    product, other = ProductFactory(), ProductFactory()
    url = f"{ADMIN}/products/{product.pk}/"
    response = manager.patch(url, {"related_product_ids": [other.pk]}, format="json")
    assert response.json()["related_product_ids"] == [other.pk]
    assert AuditLog.objects.get(action="product.update").changes["related_product_ids"] == [[], [other.pk]]
    for ids in ([product.pk], [999999]):
        bad = manager.patch(url, {"related_product_ids": ids}, format="json")
        assert bad.status_code == 400 and "related_product_ids" in error(bad)["details"]


def test_changement_vers_une_categorie_inactive_refuse(manager):
    product = ProductFactory()
    response = manager.patch(
        f"{ADMIN}/products/{product.pk}/", {"category": CategoryFactory(is_active=False).pk}, format="json"
    )
    assert response.status_code == 400


def test_put_non_autorise(manager):
    product = ProductFactory()
    assert manager.put(f"{ADMIN}/products/{product.pk}/", {}, format="json").status_code == 405


# --- Suppressions (D.4) ------------------------------------------------------------------


def test_suppression_d_un_produit_vierge(manager):
    product = ProductFactory()
    assert manager.delete(f"{ADMIN}/products/{product.pk}/").status_code == 204
    assert not Product.objects.exists()
    assert AuditLog.objects.get(action="product.delete").object_id == str(product.pk)


def test_suppression_d_un_produit_avec_historique_refusee(manager):
    product = ProductFactory(variants=False)
    variant = VariantFactory(product=product, stock_quantity=0)
    manager.post(
        f"{ADMIN}/variants/{variant.pk}/stock-adjustments/", {"delta": 5, "reason": "restock"}, format="json"
    )
    response = manager.delete(f"{ADMIN}/products/{product.pk}/")
    assert response.status_code == 409 and error(response)["code"] == "resource_in_use"
    assert "désactivez" in error(response)["message"]
    assert Product.objects.filter(pk=product.pk).exists()
    assert not AuditLog.objects.filter(action="product.delete").exists()  # trace annulée avec l'opération


def test_suppression_de_variantes(manager):
    product = ProductFactory(variants=False)
    first = VariantFactory(product=product, size="M")
    second = VariantFactory(product=product, size="L", stock_quantity=0)
    assert manager.delete(f"{ADMIN}/variants/{first.pk}/").status_code == 204
    last = manager.delete(f"{ADMIN}/variants/{second.pk}/")
    assert last.status_code == 409 and error(last)["code"] == "resource_in_use"  # dernière variante


def test_suppression_de_categories(manager):
    parent = CategoryFactory()
    child = CategoryFactory(parent=parent)
    ProductFactory(category=child)
    assert manager.delete(f"{ADMIN}/categories/{parent.pk}/").status_code == 409  # sous-catégories
    assert manager.delete(f"{ADMIN}/categories/{child.pk}/").status_code == 409  # produits
    empty = CategoryFactory()
    assert manager.delete(f"{ADMIN}/categories/{empty.pk}/").status_code == 204
    assert AuditLog.objects.filter(action="category.delete").count() == 1


# --- Catégories --------------------------------------------------------------------------


def test_categories_creation_hierarchie_et_compteurs(manager):
    created = manager.post(f"{ADMIN}/categories/", {"name": "Textile & Mode"}, format="json")
    assert created.status_code == 201 and created.json()["slug"] == "textile-mode"
    parent_id = created.json()["id"]
    child = manager.post(f"{ADMIN}/categories/", {"name": "Polos", "parent": parent_id}, format="json")
    grandchild = manager.post(
        f"{ADMIN}/categories/", {"name": "Manches", "parent": child.json()["id"]}, format="json"
    )
    assert grandchild.status_code == 400 and "parent" in error(grandchild)["details"]
    ProductFactory(category=Category.objects.get(pk=child.json()["id"]))
    listing = manager.get(f"{ADMIN}/categories/", {"root": "true"}).json()["results"]
    assert [(c["name"], c["children_count"]) for c in listing] == [("Textile & Mode", 1)]
    assert manager.get(f"{ADMIN}/categories/{child.json()['id']}/").json()["product_count"] == 1
    duplicate = manager.post(f"{ADMIN}/categories/", {"name": "Autre", "slug": "textile-mode"}, format="json")
    assert duplicate.status_code == 400 and "slug" in error(duplicate)["details"]


# --- Variantes --------------------------------------------------------------------------


def test_variantes_creation_modification_et_audit(manager):
    product = ProductFactory(variants=False, reference="INP-TEX-002")
    created = manager.post(
        f"{ADMIN}/products/{product.pk}/variants/",
        {"size": "M", "color": "Bleu", "initial_stock": 7},
        format="json",
    )
    assert created.status_code == 201
    variant = created.json()
    assert (variant["sku"], variant["stock_quantity"], variant["availability"]) == (
        "INP-TEX-002-M-BLEU",
        7,
        "in_stock",
    )
    url = f"{ADMIN}/variants/{variant['id']}/"
    patched = manager.patch(
        url, {"color": "Bleu nuit", "price_xof": 15000, "stock_quantity": 999}, format="json"
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["label"] == "M / Bleu nuit"
    assert body["sku"] == "INP-TEX-002-M-BLEU"  # SKU stable (étiquettes déjà imprimées)
    assert body["stock_quantity"] == 7  # le stock ne se modifie que par un ajustement
    assert AuditLog.objects.get(action="variant.price_change").changes == {"price_xof": [None, 15000]}
    assert AuditLog.objects.get(action="variant.update").changes == {"color": ["Bleu", "Bleu nuit"]}
    listing = manager.get(f"{ADMIN}/products/{product.pk}/variants/").json()
    assert [v["label"] for v in listing] == ["M / Bleu nuit"]
    duplicate = manager.post(
        f"{ADMIN}/products/{product.pk}/variants/", {"size": "m", "color": "BLEU NUIT"}, format="json"
    )
    assert duplicate.status_code == 400


# --- Photos -------------------------------------------------------------------------------


def test_photos_envoi_modification_ordre_suppression(manager):
    product = ProductFactory()
    url = f"{ADMIN}/products/{product.pk}/images/"
    first = manager.post(url, {"image": make_image_file(), "alt_text": "Face"}, format="multipart")
    assert first.status_code == 201, first.content
    assert first.json()["is_main"] and first.json()["thumbnail_url"].endswith(".webp")
    second = manager.post(
        url,
        {"image": make_image_file(name="dos.png", fmt="PNG"), "alt_text": "Dos", "is_main": "true"},
        format="multipart",
    )
    assert second.json()["is_main"] and second.json()["position"] == 1
    assert not ProductImage.objects.get(pk=first.json()["id"]).is_main

    ids = [second.json()["id"], first.json()["id"]]
    reordered = manager.post(f"{url}reorder/", {"ids": ids}, format="json")
    assert [image["id"] for image in reordered.json()] == ids
    for bad in ([ids[0]], [ids[0], ids[0]], [*ids, 999]):
        assert manager.post(f"{url}reorder/", {"ids": bad}, format="json").status_code == 400

    patched = manager.patch(
        f"{ADMIN}/product-images/{first.json()['id']}/", {"alt_text": "Vue de face"}, format="json"
    )
    assert patched.json()["alt_text"] == "Vue de face"
    assert manager.delete(f"{ADMIN}/product-images/{second.json()['id']}/").status_code == 204
    assert ProductImage.objects.get().is_main  # la restante devient principale


def test_photo_invalide_refusee(manager):
    product = ProductFactory()
    from django.core.files.uploadedfile import SimpleUploadedFile

    fake = SimpleUploadedFile("photo.jpg", b"pas une image", content_type="image/jpeg")
    response = manager.post(f"{ADMIN}/products/{product.pk}/images/", {"image": fake}, format="multipart")
    assert response.status_code == 400 and "image" in error(response)["details"]
    assert not ProductImage.objects.exists()


# --- Liste admin : filtres et performances ------------------------------------------------


def test_liste_admin_filtres(manager):
    SiteSettings.load()
    active = ProductFactory(name="Clé USB", variants__stock=50)
    ProductFactory(name="Archive", is_active=False)
    low = ProductFactory(name="Carnet", variants__stock=2)
    ids = lambda response: [p["id"] for p in response.json()["results"]]  # noqa: E731
    assert len(ids(manager.get(f"{ADMIN}/products/"))) == 3  # inactifs compris
    assert ids(manager.get(f"{ADMIN}/products/", {"is_active": "false"}))[0] != active.pk
    assert ids(manager.get(f"{ADMIN}/products/", {"low_stock": "true"})) == [low.pk]
    assert ids(manager.get(f"{ADMIN}/products/", {"search": "cle"})) == [active.pk]
    assert ids(manager.get(f"{ADMIN}/products/", {"category": active.category_id})) == [active.pk]
    item = manager.get(f"{ADMIN}/products/", {"search": "carnet"}).json()["results"][0]
    assert (item["total_stock"], item["variant_count"], item["availability"]) == (2, 1, "low_stock")
    assert manager.get(f"{ADMIN}/products/", {"low_stock": "oui"}).status_code == 400


def test_liste_admin_nombre_de_requetes_constant(manager):
    SiteSettings.load()

    def count():
        with CaptureQueriesContext(connection) as context:
            assert manager.get(f"{ADMIN}/products/").status_code == 200
        return len(context.captured_queries)

    for _ in range(2):
        ProductImageFactory(product=ProductFactory())
    few = count()
    for _ in range(8):
        ProductImageFactory(product=ProductFactory())
    assert count() == few
