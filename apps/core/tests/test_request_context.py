import uuid

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.request import Request

from apps.core.middleware import VisitorHeaderMiddleware
from apps.core.request_context import (
    get_app_version,
    get_client_ip,
    get_client_platform,
    get_visitor_id,
)

VALID_V4 = "c0a8f1e2-5b7d-4c11-9e0a-2f6d3b8a9c10"


@pytest.fixture
def rf():
    return RequestFactory()


def test_visitor_id_valide_conserve(rf):
    context = get_visitor_id(rf.get("/", HTTP_X_VISITOR_ID=VALID_V4))
    assert str(context.visitor_id) == VALID_V4
    assert context.is_new is False


def test_visitor_id_majuscules_normalise(rf):
    context = get_visitor_id(rf.get("/", HTTP_X_VISITOR_ID=VALID_V4.upper()))
    assert str(context.visitor_id) == VALID_V4
    assert context.is_new is False


@pytest.mark.parametrize(
    "header",
    [
        "pas-un-uuid",
        "",
        str(uuid.uuid1()),  # UUID valide mais pas v4 (contient l'horodatage et l'adresse MAC)
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_visitor_id_invalide_remplace(rf, header):
    context = get_visitor_id(rf.get("/", HTTP_X_VISITOR_ID=header))
    assert context.is_new is True
    assert context.visitor_id.version == 4
    assert str(context.visitor_id) != header


def test_visitor_id_absent_genere(rf):
    context = get_visitor_id(rf.get("/"))
    assert context.is_new is True
    assert context.visitor_id.version == 4


def test_visitor_id_stable_pendant_la_requete_et_via_request_drf(rf):
    http_request = rf.get("/")
    first = get_visitor_id(Request(http_request))
    assert get_visitor_id(http_request) == first
    assert http_request.visitor_id == str(first.visitor_id)


def test_middleware_renvoie_l_identifiant_attribue(rf):
    def view(request):
        get_visitor_id(request)
        return HttpResponse("ok")

    request = rf.get("/")
    response = VisitorHeaderMiddleware(view)(request)
    assert response["X-Visitor-Id"] == request.visitor_id


def test_middleware_sans_identifiant_n_ajoute_rien(rf):
    response = VisitorHeaderMiddleware(lambda request: HttpResponse("ok"))(rf.get("/"))
    assert "X-Visitor-Id" not in response


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("web", "web"),
        ("Android", "android"),
        (" IOS ", "ios"),
        ("windows", "unknown"),
        ("unknown", "unknown"),
        (None, "unknown"),
    ],
)
def test_client_platform(rf, header, expected):
    extra = {"HTTP_X_CLIENT_PLATFORM": header} if header is not None else {}
    assert get_client_platform(rf.get("/", **extra)) == expected


def test_client_ip_local_ignore_x_forwarded_for(rf):
    # NUM_PROXIES=0 (développement) : l'en-tête X-Forwarded-For, falsifiable, est ignoré.
    request = rf.get("/", REMOTE_ADDR="192.168.1.10", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert get_client_ip(request) == "192.168.1.10"
    assert get_client_ip(Request(request)) == "192.168.1.10"


def test_client_ip_invalide(rf):
    assert get_client_ip(rf.get("/", REMOTE_ADDR="pas-une-ip")) is None


@pytest.mark.parametrize(
    ("header", "expected"), [("1.2.0", "1.2.0"), ("2", "2"), ("1.2.0-beta", None), ("<script>", None)]
)
def test_app_version(rf, header, expected):
    assert get_app_version(rf.get("/", HTTP_X_APP_VERSION=header)) == expected
