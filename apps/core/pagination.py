from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """?page=1&page_size=20 (max 100) ; réponse {count, next, previous, results}."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
