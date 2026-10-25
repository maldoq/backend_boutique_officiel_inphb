from unittest import mock

import pytest
from django.contrib.auth.models import Group

from apps.core import codes
from apps.core.codes import ALPHABET, CodeGenerationError, random_code, unique_code


def test_alphabet_sans_caracteres_ambigus():
    for ambiguous in "0O1I":
        assert ambiguous not in ALPHABET


def test_random_code_longueur_et_alphabet():
    code = random_code(10)
    assert len(code) == 10
    assert set(code) <= set(ALPHABET)


def test_random_code_longueur_invalide():
    with pytest.raises(ValueError):
        random_code(0)


def test_random_code_non_previsible():
    assert len({random_code(10) for _ in range(200)}) == 200


@pytest.mark.django_db
def test_unique_code_avec_prefixe():
    code = unique_code(Group, "name", 8, prefix="CMD-")
    assert code.startswith("CMD-")
    assert len(code) == 12


@pytest.mark.django_db
def test_unique_code_evite_un_code_existant():
    Group.objects.create(name="AAAAAA")
    with mock.patch.object(codes, "random_code", side_effect=["AAAAAA", "BBBBBB"]):
        assert unique_code(Group, "name", 6) == "BBBBBB"


@pytest.mark.django_db
def test_unique_code_echoue_apres_les_essais():
    Group.objects.create(name="AAAAAA")
    with mock.patch.object(codes, "random_code", return_value="AAAAAA"):
        with pytest.raises(CodeGenerationError):
            unique_code(Group, "name", 6, attempts=3)
