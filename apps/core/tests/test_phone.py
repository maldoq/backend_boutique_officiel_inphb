import pytest
from django.core.exceptions import ValidationError

from apps.core.phone import InvalidPhoneNumber, normalize_phone, validate_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0700000000", "+2250700000000"),
        ("07 00 00 00 00", "+2250700000000"),
        ("07.00.00.00.00", "+2250700000000"),
        ("07-00-00-00-00", "+2250700000000"),
        ("+225 07 00 00 00 00", "+2250700000000"),
        ("002250700000000", "+2250700000000"),
        ("2250700000000", "+2250700000000"),
        ("+33 6 12 34 56 78", "+33612345678"),
        ("0033612345678", "+33612345678"),
        ("+1 (202) 555-0143", "+12025550143"),
        (" 07 00 00 00 00 ", "+2250700000000"),  # espaces insécables (copier-coller)
    ],
)
def test_normalize_phone_formats_acceptes(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "07000000",  # ancien format ivoirien à 8 chiffres
        "+22507000000",  # +225 suivi de 9 chiffres seulement
        "+2250700000000123",  # trop long
        "+0123456789",  # indicatif ne peut commencer par 0
        "12345",
        None,
    ],
)
def test_normalize_phone_formats_refuses(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


def test_validate_phone_leve_une_validation_error_django():
    validate_phone("0700000000")
    with pytest.raises(ValidationError):
        validate_phone("123")
