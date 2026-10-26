from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from PIL import Image

from apps.catalog.choices import Availability
from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.catalog.tests.factories import (
    CategoryFactory,
    ProductFactory,
    ProductImageFactory,
    VariantFactory,
    make_image_file,
)
from apps.core.models import SiteSettings

pytestmark = pytest.mark.django_db


def assert_db_rejects(callable_):
    with pytest.raises(IntegrityError), transaction.atomic():
        callable_()


# --- Variantes : libellé, options, SKU --------------------------------------------


def test_libelle_standard_et_options():
    product = ProductFactory(variants=False, reference="INP-TEX-001")
    assert VariantFactory(product=product).label == "Standard"
    assert VariantFactory(product=product, size="M", color="Vert").label == "M / Vert"
    assert VariantFactory(product=product, size="L", color="Vert", model="Brodé").label == "L / Vert / Brodé"


def test_options_nettoyees_et_unicite_sans_tenir_compte_des_majuscules():
    product = ProductFactory(variants=False)
    variant = VariantFactory(product=product, size="  M ", color="Vert   foncé")
    assert (variant.size, variant.color) == ("M", "Vert foncé")
    assert_db_rejects(lambda: VariantFactory(product=product, size="m", color="VERT FONCÉ".lower()))
    duplicate = ProductVariant(product=product, size="m", color="vert foncé", sku="AUTRE-SKU")
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_meme_combinaison_autorisee_sur_un_autre_produit():
    VariantFactory(size="M", color="Vert")
    VariantFactory(size="M", color="Vert")  # autre produit (SubFactory)
    assert ProductVariant.objects.count() == 2


def test_une_seule_variante_standard_par_produit():
    product = ProductFactory()  # crée déjà « Standard »
    assert_db_rejects(lambda: VariantFactory(product=product))


def test_sku_genere_depuis_reference_et_options():
    product = ProductFactory(variants=False, reference="INP-TEX-001")
    assert VariantFactory(product=product, size="M", color="Vert").sku == "INP-TEX-001-M-VERT"
    assert VariantFactory(product=product, size="XL", color="Bleu clair").sku == "INP-TEX-001-XL-BLEU-CLAIR"
    assert VariantFactory(product=product).sku == "INP-TEX-001"


def test_sku_genere_unique_et_sku_saisi_normalise():
    ProductVariant.objects.create(product=ProductFactory(variants=False), sku="INP-TEX-001-M")
    product = ProductFactory(variants=False, reference="INP-TEX-001")
    assert VariantFactory(product=product, size="M").sku == "INP-TEX-001-M-2"
    assert VariantFactory(product=product, size="S", sku=" inp tex 001 s ").sku == "INP-TEX-001-S"


def test_sku_toujours_renseigne_en_base_et_genere_des_la_validation():
    variant = VariantFactory(size="M")
    assert_db_rejects(lambda: ProductVariant.objects.filter(pk=variant.pk).update(sku=""))
    assert_db_rejects(lambda: ProductVariant.objects.filter(pk=variant.pk).update(sku=None))
    product = ProductFactory(variants=False, reference="INP-ACC-002")
    draft = ProductVariant(product=product, size="Unique", sku="")
    draft.full_clean()
    assert draft.sku == "INP-ACC-002-UNIQUE"


def test_sku_caracteres_invalides():
    variant = ProductVariant(product=ProductFactory(variants=False), sku="SKU/É")
    with pytest.raises(ValidationError) as info:
        variant.full_clean()
    assert "sku" in info.value.message_dict


# --- Produit : référence, slug -----------------------------------------------------


def test_reference_normalisee():
    assert ProductFactory(reference=" inp tex 001 ").reference == "INP-TEX-001"


def test_slug_genere_unique_et_stable():
    first = ProductFactory(name="Clé USB 32 Go INP-HB")
    second = ProductFactory(name="Clé USB 32 Go INP-HB")
    assert first.slug == "cle-usb-32-go-inp-hb"
    assert second.slug == "cle-usb-32-go-inp-hb-2"
    first.name = "Clé USB 64 Go INP-HB"
    first.save()
    assert first.slug == "cle-usb-32-go-inp-hb"  # liens et QR déjà diffusés : le slug ne change pas


def test_slug_saisi_normalise():
    assert ProductFactory(slug="Polo Vert Édition 2026").slug == "polo-vert-edition-2026"


# --- Prix ------------------------------------------------------------------------


def test_prix_effectif():
    product = ProductFactory(variants=False, price_xof=12000)
    assert VariantFactory(product=product, size="M").effective_price_xof == 12000
    assert VariantFactory(product=product, size="XXL", price_xof=14000).effective_price_xof == 14000


def test_prix_contraintes_en_base():
    product = ProductFactory()
    assert_db_rejects(lambda: Product.objects.filter(pk=product.pk).update(price_xof=0))
    assert_db_rejects(lambda: Product.objects.filter(pk=product.pk).update(compare_at_price_xof=12000))
    assert_db_rejects(lambda: ProductVariant.objects.filter(product=product).update(price_xof=0))
    Product.objects.filter(pk=product.pk).update(compare_at_price_xof=15000)  # > prix : accepté


def test_prix_barre_controle_en_validation():
    product = ProductFactory.build(price_xof=12000, compare_at_price_xof=10000, category=CategoryFactory())
    with pytest.raises(ValidationError) as info:
        product.full_clean()
    assert "compare_at_price_xof" in info.value.message_dict


def test_promotion_calculee_sur_le_prix_reellement_paye():
    product = ProductFactory(variants=False, price_xof=12000, compare_at_price_xof=15000)
    VariantFactory(product=product, size="M")
    assert product.is_on_sale and product.min_price_xof == 12000
    expensive = ProductFactory(variants=False, price_xof=12000, compare_at_price_xof=15000)
    VariantFactory(product=expensive, size="M", price_xof=16000)
    assert not expensive.is_on_sale  # le prix payé dépasse le prix barré


# --- Stock et disponibilité ------------------------------------------------------


def test_stock_jamais_negatif_en_base():
    variant = VariantFactory()
    assert_db_rejects(lambda: ProductVariant.objects.filter(pk=variant.pk).update(stock_quantity=-1))


@pytest.mark.parametrize(
    ("stock", "coming_soon", "expected"),
    [
        (20, False, Availability.IN_STOCK),
        (3, False, Availability.LOW_STOCK),  # seuil par défaut : 3
        (0, False, Availability.OUT_OF_STOCK),
        (20, True, Availability.COMING_SOON),
    ],
)
def test_disponibilite_des_4_etats(stock, coming_soon, expected):
    variant = VariantFactory(stock_quantity=stock, product__is_coming_soon=coming_soon)
    assert variant.availability == expected
    assert variant.availability_label == Availability(expected).label


def test_seuil_specifique_et_seuil_de_la_boutique():
    site = SiteSettings.load()
    site.default_low_stock_threshold = 10
    site.save()
    assert VariantFactory(stock_quantity=8).availability == Availability.LOW_STOCK
    assert VariantFactory(stock_quantity=8, low_stock_threshold=2).availability == Availability.IN_STOCK


def test_disponibilite_produit_meilleure_variante_active():
    product = ProductFactory(variants=False)
    VariantFactory(product=product, size="S", stock_quantity=0)
    VariantFactory(product=product, size="M", stock_quantity=2)
    VariantFactory(product=product, size="L", stock_quantity=50, is_active=False)  # ignorée
    assert product.availability == Availability.LOW_STOCK
    assert product.availability_label == "Stock limité"


def test_produit_sans_variante_active_en_rupture():
    assert ProductFactory(variants=False).availability == Availability.OUT_OF_STOCK
    assert ProductFactory(variants=False, is_coming_soon=True).availability == Availability.COMING_SOON


def test_seuil_par_defaut_lu_une_seule_fois(django_assert_num_queries):
    product = ProductFactory(variants=False)
    for size in ("S", "M", "L", "XL"):
        VariantFactory(product=product, size=size, stock_quantity=5)
    SiteSettings.load()  # ligne de paramètres déjà créée, comme en exploitation
    product = Product.objects.prefetch_related("variants").get(pk=product.pk)
    with django_assert_num_queries(1):  # SiteSettings, pas une requête par variante
        assert product.availability == Availability.IN_STOCK


# --- Catégories -------------------------------------------------------------------


def test_categorie_slug_et_un_seul_niveau():
    textile = Category.objects.create(name="Textile")
    polos = Category.objects.create(name="Polos & T-shirts", parent=textile)
    assert polos.slug == "polos-t-shirts"
    with pytest.raises(ValidationError):
        Category.objects.create(name="Manches longues", parent=polos)


def test_categorie_ni_sa_propre_parente_ni_parente_si_elle_a_des_enfants():
    textile = Category.objects.create(name="Textile")
    Category.objects.create(name="Polos", parent=textile)
    textile.parent = textile
    with pytest.raises(ValidationError):
        textile.full_clean()
    textile.parent = Category.objects.create(name="Boutique")
    with pytest.raises(ValidationError):
        textile.save()


def test_categorie_utilisee_non_supprimable():
    product = ProductFactory()
    with pytest.raises(ProtectedError):
        product.category.delete()


def test_produit_associe_a_lui_meme_refuse():
    product, other = ProductFactory(), ProductFactory()
    product.related_products.add(other)
    with pytest.raises(ValidationError), transaction.atomic():
        product.related_products.add(product)
    assert list(product.related_products.all()) == [other]


# --- Images ---------------------------------------------------------------------


def test_image_reencodee_sans_exif_avec_miniature_et_nom_aleatoire():
    exif = Image.Exif()
    exif[0x010F] = "AppareilSecret"
    image = ProductImageFactory(
        image=make_image_file(name="IMG_de_Awa_Kone.jpg", size=(1600, 1200), exif=exif.tobytes())
    )
    assert (image.width, image.height) == (1600, 1200)
    assert image.image.name.startswith("products/") and "Awa" not in image.image.name
    with Image.open(image.image.path) as stored:
        assert not stored.getexif()
    with Image.open(BytesIO(image.thumbnail.read())) as thumb:
        assert thumb.format == "WEBP" and thumb.size == (400, 300)


def test_image_invalide_refusee_en_validation():
    image = ProductImage(product=ProductFactory(), image=make_image_file(name="x.gif", fmt="GIF"))
    with pytest.raises(ValidationError) as info:
        image.full_clean()
    assert "image" in info.value.message_dict


def test_premiere_image_principale_puis_remplacement():
    product = ProductFactory()
    first = ProductImageFactory(product=product)
    second = ProductImageFactory(product=product)
    first.refresh_from_db()
    assert first.is_main and not second.is_main
    second.is_main = True
    second.save()
    first.refresh_from_db()
    assert second.is_main and not first.is_main
    assert product.main_image == second


def test_suppression_image_principale_promeut_la_suivante_et_efface_les_fichiers(
    django_capture_on_commit_callbacks,
):
    product = ProductFactory()
    main = ProductImageFactory(product=product, position=0)
    other = ProductImageFactory(product=product, position=1)
    storage, paths = main.image.storage, [main.image.name, main.thumbnail.name]
    with django_capture_on_commit_callbacks(execute=True):
        main.delete()
    other.refresh_from_db()
    assert other.is_main
    assert not any(storage.exists(path) for path in paths)


def test_remplacement_du_fichier_efface_l_ancien(django_capture_on_commit_callbacks):
    image = ProductImageFactory()
    storage, old_paths = image.image.storage, [image.image.name, image.thumbnail.name]
    with django_capture_on_commit_callbacks(execute=True):
        image.image = make_image_file(name="nouvelle.png", fmt="PNG")
        image.save()
    assert image.image.name.endswith(".png")
    assert not any(storage.exists(path) for path in old_paths)
    assert storage.exists(image.image.name) and storage.exists(image.thumbnail.name)
