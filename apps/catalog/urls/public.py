from django.urls import path

from apps.catalog.views.public import (
    CategoryListView,
    ProductDetailView,
    ProductListView,
    RelatedProductListView,
)

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="catalog-categories"),
    path("products/", ProductListView.as_view(), name="catalog-products"),
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="catalog-product-detail"),
    path("products/<slug:slug>/related/", RelatedProductListView.as_view(), name="catalog-product-related"),
]
