import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.core.models import SiteSettings


@pytest.mark.django_db
def test_load_cree_la_ligne_unique_avec_les_valeurs_par_defaut():
    site = SiteSettings.load()
    assert site.pk == 1
    assert site.shop_name == "Boutique INP-HB"
    assert site.slogan == "FORMER – INNOVER – PRODUIRE"
    assert site.pickup_hold_days == 7
    assert site.maintenance_mode is False
    assert SiteSettings.load().pk == site.pk
    assert SiteSettings.objects.count() == 1


@pytest.mark.django_db
@override_settings(DEFAULT_LOW_STOCK_THRESHOLD=5)
def test_seuil_initial_repris_de_l_environnement():
    assert SiteSettings.load().default_low_stock_threshold == 5


@pytest.mark.django_db
def test_singleton_meme_si_on_cree_une_autre_instance():
    original = SiteSettings.load()
    SiteSettings(shop_name="Autre").save()
    assert SiteSettings.objects.count() == 1
    reloaded = SiteSettings.load()
    assert reloaded.shop_name == "Autre"
    assert reloaded.created_at == original.created_at


@pytest.mark.django_db
def test_suppression_interdite():
    with pytest.raises(ValidationError):
        SiteSettings.load().delete()
    assert SiteSettings.objects.count() == 1


@pytest.mark.django_db
def test_telephone_de_contact_normalise_et_valide():
    site = SiteSettings.load()
    site.contact_phone = "07 00 00 00 00"
    site.full_clean()
    assert site.contact_phone == "+2250700000000"
    site.contact_phone = "123"
    with pytest.raises(ValidationError):
        site.full_clean()
