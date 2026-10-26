"""API publique du catalogue (étape 6) : contrat G.4, visibilité, filtres, performances, sécurité."""

import itertools

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Category, Product
from apps.catalog.selectors import annotate_listing
from apps.catalog.tests.factories import (
    CategoryFactory,
    ProductFactory,
    ProductImageFactory,
    VariantFactory,
)
from apps.core.models import SiteSettings

pytestmark = pytest.mark.django_db

PRODUCTS = "/api/v1/products/"
CATEGORIES = "/api/v1/categories/"
FORBIDDEN_KEYS = {"stock_quantity", "low_stock_threshold", "created_by", "search_text", "threshold"}
LIST_KEYS = {
    "id",
    "slug",
    "reference",
    "name",
    "short_description",
    "category",
    "price_xof",
    "compare_at_price_xof",
    "min_price_xof",
    "is_on_sale",
    "currency",
    "main_image",
    "availability",
    "availability_label",
    "is_coming_soon",
    "has_variants",
}


def all_keys(data):
    if isinstance(data, dict):
        return set(data) | set().union(*(all_keys(v) for v in data.values()))
    if isinstance(data, list):
        return set().union(*(all_keys(v) for v in data)) if data else set()
    return set()


def slugs(response):
    return [item["slug"] for item in response.json()["results"]]


def polo(**overrides):
    """Polo vert : M (stock 20), XL (rupture), XXL (prix spécifique), une variante inactive."""
    product = ProductFactory(
        variants=False,
        name="Polo INP-HB Vert",
        reference="INP-TEX-001",
        price_xof=12000,
        compare_at_price_xof=15000,
        **overrides,
    )
    VariantFactory(product=product, size="M", color="Vert", stock_quantity=20, position=1)
    VariantFactory(product=product, size="XL", color="Vert", stock_quantity=0, position=2)
    VariantFactory(product=product, size="XXL", color="Vert", stock_quantity=4, price_xof=14000, position=3)
    VariantFactory(product=product, size="S", color="Vert", stock_quantity=50, is_active=False, position=0)
    return product


# --- Liste ------------------------------------------------------------------------


def test_liste_vide(api_client):
    response = api_client.get(PRODUCTS)
    assert response.status_code == 200
    assert response.json() == {"count": 0, "next": None, "previous": None, "results": []}


def test_carte_produit_conforme_au_contrat(api_client):
    product = polo()
    ProductImageFactory(product=product, alt_text="Polo vert INP-HB")
    item = api_client.get(PRODUCTS).json()["results"][0]
    assert set(item) == LIST_KEYS
    assert item["category"] == {
        "id": product.category.id,
        "slug": product.category.slug,
        "name": product.category.name,
    }
    assert (item["price_xof"], item["compare_at_price_xof"], item["min_price_xof"]) == (12000, 15000, 12000)
    assert item["is_on_sale"] is True
    assert item["currency"] == "XOF"
    assert item["availability"] == "in_stock" and item["availability_label"] == "En stock"
    assert item["has_variants"] is True
    image = item["main_image"]
    assert set(image) == {"url", "thumbnail_url", "alt", "width", "height"}
    assert image["url"].startswith("http://testserver/media/products/")
    assert image["thumbnail_url"].endswith(".webp")
    assert image["alt"] == "Polo vert INP-HB"


def test_produit_standard_sans_option_et_sans_image(api_client):
    ProductFactory(name="Mug INP-HB")
    item = api_client.get(PRODUCTS).json()["results"][0]
    assert item["has_variants"] is False
    assert item["main_image"] is None


@pytest.mark.parametrize(
    "hide",
    [
        lambda p: Product.objects.filter(pk=p.pk).update(is_active=False),
        lambda p: Category.objects.filter(pk=p.category_id).update(is_active=False),
        lambda p: Category.objects.filter(pk=p.category.parent_id).update(is_active=False),
    ],
    ids=["produit_inactif", "categorie_inactive", "categorie_parente_inactive"],
)
def test_produits_masques(api_client, hide):
    parent = CategoryFactory(name="Textile")
    product = ProductFactory(category=CategoryFactory(name="Polos", parent=parent))
    hide(product)
    assert api_client.get(PRODUCTS).json()["count"] == 0
    response = api_client.get(f"{PRODUCTS}{product.slug}/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_aucune_donnee_interne_exposee(api_client):
    product = polo()
    ProductImageFactory(product=product)
    other = ProductFactory()
    product.related_products.add(other)
    responses = [
        api_client.get(PRODUCTS),
        api_client.get(f"{PRODUCTS}{product.slug}/"),
        api_client.get(f"{PRODUCTS}{product.slug}/related/"),
        api_client.get(CATEGORIES),
    ]
    for response in responses:
        assert response.status_code == 200
        assert not (all_keys(response.json()) & FORBIDDEN_KEYS)
        assert b"stock_quantity" not in response.content


# --- Filtres, recherche, tri, pagination --------------------------------------------


def test_recherche_sans_accents_par_nom_reference_et_sku(api_client):
    ProductFactory(name="Clé USB 32 Go INP-HB", reference="INP-ACC-004")
    polo()
    assert slugs(api_client.get(PRODUCTS, {"search": "cle usb"})) == ["cle-usb-32-go-inp-hb"]
    assert slugs(api_client.get(PRODUCTS, {"search": "CLÉ 32"})) == ["cle-usb-32-go-inp-hb"]
    assert slugs(api_client.get(PRODUCTS, {"search": "inp-acc-004"})) == ["cle-usb-32-go-inp-hb"]
    assert slugs(api_client.get(PRODUCTS, {"search": "INP-TEX-001-XXL"})) == ["polo-inp-hb-vert"]
    assert slugs(api_client.get(PRODUCTS, {"search": "cle polo"})) == []  # tous les mots requis


def test_filtre_categorie_inclut_les_sous_categories(api_client):
    textile = CategoryFactory(name="Textile")
    polos = CategoryFactory(name="Polos", parent=textile)
    in_parent = ProductFactory(name="Sweat", category=textile)
    in_child = ProductFactory(name="Polo", category=polos)
    ProductFactory(name="Mug")
    assert set(slugs(api_client.get(PRODUCTS, {"category": textile.slug}))) == {in_parent.slug, in_child.slug}
    assert slugs(api_client.get(PRODUCTS, {"category": polos.slug})) == [in_child.slug]
    assert slugs(api_client.get(PRODUCTS, {"category": "inconnue"})) == []


def test_filtres_prix_sur_le_prix_reellement_paye(api_client):
    cheap_polo = ProductFactory(variants=False, name="Polo", price_xof=12000)
    VariantFactory(product=cheap_polo, size="XXL", price_xof=9000)  # seule variante : 9 000
    ProductFactory(name="Sweat", price_xof=20000)
    assert slugs(api_client.get(PRODUCTS, {"max_price": 10000})) == ["polo"]
    assert slugs(api_client.get(PRODUCTS, {"min_price": 10000})) == ["sweat"]
    assert slugs(api_client.get(PRODUCTS, {"ordering": "price"})) == ["polo", "sweat"]
    assert slugs(api_client.get(PRODUCTS, {"ordering": "-price"})) == ["sweat", "polo"]


def test_filtres_disponibilite_et_mise_en_avant(api_client):
    ProductFactory(name="En stock", is_featured=True)
    ProductFactory(name="Rupture", variants__stock=0)
    ProductFactory(name="Bientot", is_coming_soon=True)
    assert slugs(api_client.get(PRODUCTS, {"availability": "out_of_stock"})) == ["rupture"]
    assert slugs(api_client.get(PRODUCTS, {"availability": "coming_soon"})) == ["bientot"]
    assert slugs(api_client.get(PRODUCTS, {"featured": "true"})) == ["en-stock"]


def test_tri_par_defaut_puis_pagination(api_client):
    for name in ("Carnet", "Badge", "Agenda"):
        ProductFactory(name=name)
    ProductFactory(name="Zèbre", is_featured=True)
    response = api_client.get(PRODUCTS, {"page_size": 2})
    assert response.json()["count"] == 4
    assert slugs(response) == ["zebre", "agenda"]  # mis en avant d'abord, puis par nom
    assert slugs(api_client.get(PRODUCTS, {"page_size": 2, "page": 2})) == ["badge", "carnet"]
    assert slugs(api_client.get(PRODUCTS, {"ordering": "-name"}))[0] == "zebre"


@pytest.mark.parametrize(
    "params",
    [
        {"min_price": 20000, "max_price": 10000},
        {"min_price": -1},
        {"availability": "disponible"},
        {"ordering": "stock_quantity"},
        {"featured": "peut-etre"},
    ],
)
def test_parametres_invalides_400(api_client, params):
    response = api_client.get(PRODUCTS, params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


# --- Disponibilité calculée en base = règle du modèle ------------------------------


def test_disponibilite_en_base_identique_au_modele():
    site = SiteSettings.load()
    site.default_low_stock_threshold = 3
    site.save()
    scenarios = itertools.product([0, 2, 3, 4, 50], [None, 1, 10], [True, False], [False, True])
    for stock, own_threshold, active, coming_soon in scenarios:
        product = ProductFactory(variants=False, is_coming_soon=coming_soon)
        VariantFactory(
            product=product,
            size="A",
            stock_quantity=stock,
            low_stock_threshold=own_threshold,
            is_active=active,
        )
        VariantFactory(product=product, size="B", stock_quantity=1)
    annotated = annotate_listing(Product.objects.prefetch_related("variants"), 3)
    for product in annotated:
        assert product.availability_code == product.availability, product.pk
        assert product.price_from == product.min_price_xof


# --- Fiche produit -----------------------------------------------------------------


def test_fiche_produit_complete(api_client):
    product = polo()
    second = ProductImageFactory(product=product, position=2, alt_text="Dos")
    main = ProductImageFactory(product=product, position=1, alt_text="Face", is_main=True)
    response = api_client.get(f"{PRODUCTS}{product.slug}/")
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == product.description
    assert [image["id"] for image in data["images"]] == [main.id, second.id]
    assert data["images"][0]["is_main"] is True
    assert data["options"] == {"sizes": ["M", "XL", "XXL"], "colors": ["Vert"], "models": []}
    variants = {v["label"]: v for v in data["variants"]}
    assert set(variants) == {"M / Vert", "XL / Vert", "XXL / Vert"}  # variante inactive absente
    assert variants["M / Vert"]["max_orderable_quantity"] == 10  # min(20, MAX_QTY_PER_LINE)
    assert variants["XL / Vert"]["availability"] == "out_of_stock"
    assert variants["XL / Vert"]["max_orderable_quantity"] == 0
    assert variants["XXL / Vert"]["price_xof"] == 14000
    assert variants["XXL / Vert"]["availability"] == "in_stock"  # 4 > seuil 3
    assert variants["XXL / Vert"]["max_orderable_quantity"] == 4
    assert data["seo"] == {
        "title": "Polo INP-HB Vert | Boutique INP-HB",
        "description": product.short_description,
        "canonical_path": "/produits/polo-inp-hb-vert",
    }


def test_bientot_disponible_non_commandable(api_client):
    product = ProductFactory(is_coming_soon=True)
    data = api_client.get(f"{PRODUCTS}{product.slug}/").json()
    assert data["availability"] == "coming_soon" and data["availability_label"] == "Bientôt disponible"
    assert data["variants"][0]["max_orderable_quantity"] == 0


def test_produit_inconnu_404(api_client):
    response = api_client.get(f"{PRODUCTS}inexistant/")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Ressource introuvable.", "details": {}}
    }
    assert "Cache-Control" not in response or "max-age=60" not in response["Cache-Control"]


def test_produits_associes_explicites_ou_meme_categorie(api_client):
    category = CategoryFactory()
    product = ProductFactory(category=category)
    neighbours = [ProductFactory(category=category, name=f"Voisin {i}") for i in range(5)]
    data = api_client.get(f"{PRODUCTS}{product.slug}/").json()
    assert len(data["related_products"]) == 4  # aucun associé : 4 de la même catégorie
    assert product.slug not in [p["slug"] for p in data["related_products"]]

    hidden = ProductFactory(is_active=False)
    product.related_products.add(neighbours[4], hidden)
    related = api_client.get(f"{PRODUCTS}{product.slug}/related/").json()
    assert [p["slug"] for p in related] == [neighbours[4].slug]
    assert set(related[0]) == LIST_KEYS
    embedded = api_client.get(f"{PRODUCTS}{product.slug}/").json()["related_products"]
    assert [p["slug"] for p in embedded] == [neighbours[4].slug]
    assert set(embedded[0]) == {"id", "slug", "name", "price_xof", "min_price_xof", "main_image"}


# --- Catégories ---------------------------------------------------------------------


def test_arbre_des_categories(api_client):
    textile = CategoryFactory(name="Textile", position=1)
    polos = CategoryFactory(name="Polos", parent=textile)
    hidden_child = CategoryFactory(name="Archives", parent=textile, is_active=False)
    papeterie = CategoryFactory(name="Papeterie", position=2)
    closed = CategoryFactory(name="Fermée", is_active=False)
    CategoryFactory(name="Orpheline", parent=closed)
    ProductFactory(category=textile)
    ProductFactory(category=polos)
    ProductFactory(category=polos, is_active=False)
    ProductFactory(category=hidden_child)

    data = api_client.get(CATEGORIES).json()
    assert [c["name"] for c in data] == ["Textile", "Papeterie"]
    assert data[0]["product_count"] == 2  # 1 direct + 1 dans « Polos »
    assert [c["name"] for c in data[0]["children"]] == ["Polos"]
    assert data[0]["children"][0]["product_count"] == 1
    assert data[1] == {
        "id": papeterie.id,
        "slug": "papeterie",
        "name": "Papeterie",
        "description": "",
        "image_url": None,
        "product_count": 0,
        "children": [],
    }


# --- Transverse : cache, URL absolues, web = mobile, performances -------------------


def test_cache_public_60_secondes(api_client):
    product = ProductFactory()
    for url in (PRODUCTS, CATEGORIES, f"{PRODUCTS}{product.slug}/", f"{PRODUCTS}{product.slug}/related/"):
        assert api_client.get(url)["Cache-Control"] == "public, max-age=60", url


@override_settings(
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), ALLOWED_HOSTS=["api.boutique.test"]
)
def test_urls_absolues_en_https_derriere_nginx(api_client):
    ProductImageFactory()
    # Nginx transmet Host et X-Forwarded-Proto (proxy_set_header) : URL https sans port.
    response = api_client.get(PRODUCTS, HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="api.boutique.test")
    assert response.json()["results"][0]["main_image"]["url"].startswith("https://api.boutique.test/media/")


def test_meme_reponse_pour_le_web_et_le_mobile(api_client):
    """T01 : mêmes données pour un client web et un client Android."""
    product = polo()
    ProductImageFactory(product=product)
    for url in (PRODUCTS, f"{PRODUCTS}{product.slug}/", CATEGORIES):
        web = api_client.get(url, HTTP_X_CLIENT_PLATFORM="web").json()
        android = api_client.get(url, HTTP_X_CLIENT_PLATFORM="android", HTTP_X_APP_VERSION="1.0.0").json()
        assert web == android


def _count_queries(api_client, url):
    with CaptureQueriesContext(connection) as context:
        assert api_client.get(url).status_code == 200
    return len(context.captured_queries)


def test_nombre_de_requetes_constant(api_client):
    SiteSettings.load()

    def add_products(count):
        for _ in range(count):
            product = ProductFactory(variants=False)
            VariantFactory(product=product, size="M")
            VariantFactory(product=product, size="L", stock_quantity=1)
            ProductImageFactory(product=product)

    add_products(2)
    few = _count_queries(api_client, PRODUCTS)
    add_products(10)
    many = _count_queries(api_client, PRODUCTS)
    assert few == many <= 4

    product = Product.objects.first()
    product.related_products.add(*Product.objects.exclude(pk=product.pk)[:5])
    assert _count_queries(api_client, f"{PRODUCTS}{product.slug}/") <= 8
    assert _count_queries(api_client, CATEGORIES) <= 3
