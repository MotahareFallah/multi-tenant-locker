from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """50 per page, fixed: a client cannot ask for an unbounded page."""

    page_size = 50
