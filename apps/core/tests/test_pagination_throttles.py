import pytest
from django.core.cache import cache
from django.test import RequestFactory
from rest_framework.request import Request

from apps.core.pagination import StandardPagination
from apps.core.throttles import LoginThrottle


@pytest.mark.parametrize(("query", "expected"), [("", 20), ("?page_size=50", 50), ("?page_size=500", 100)])
def test_pagination_taille_par_defaut_et_maximum(query, expected):
    paginator = StandardPagination()
    request = Request(RequestFactory().get(f"/{query}"))
    page = paginator.paginate_queryset(list(range(250)), request)
    assert len(page) == expected
    response = paginator.get_paginated_response(page)
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 250


def test_throttle_compte_par_ip():
    class TwoPerMinute(LoginThrottle):
        rate = "2/min"

    cache.clear()
    rf = RequestFactory()
    same_ip = [Request(rf.get("/", REMOTE_ADDR="10.0.0.1")) for _ in range(3)]
    other_ip = Request(rf.get("/", REMOTE_ADDR="10.0.0.2"))

    results = [TwoPerMinute().allow_request(request, None) for request in same_ip]
    assert results == [True, True, False]
    assert TwoPerMinute().allow_request(other_ip, None) is True
