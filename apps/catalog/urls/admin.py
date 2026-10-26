from rest_framework.routers import SimpleRouter

from apps.catalog.views.admin import (
    AdminCategoryViewSet,
    AdminProductImageViewSet,
    AdminProductViewSet,
    AdminVariantViewSet,
)

router = SimpleRouter()
router.register("categories", AdminCategoryViewSet, basename="admin-category")
router.register("products", AdminProductViewSet, basename="admin-product")
router.register("variants", AdminVariantViewSet, basename="admin-variant")
router.register("product-images", AdminProductImageViewSet, basename="admin-product-image")

urlpatterns = router.urls
