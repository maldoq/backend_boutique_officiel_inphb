"""Django Admin du stock : historique en lecture seule et ajustement via le service (étape 7).

`inventory` vient après `catalog` (C.2) : c'est ici qu'on ajoute le lien « Ajuster le stock »
à la fiche produit, sans que le catalogue dépende du stock.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from rest_framework.exceptions import ValidationError

from apps.catalog.admin import ProductAdmin as CatalogProductAdmin
from apps.catalog.admin import ProductVariantInline as CatalogVariantInline
from apps.catalog.models import Product, ProductVariant
from apps.core.exceptions import BusinessError

from .forms import StockAdjustmentForm
from .models import StockMovement
from .services import adjust_stock

HISTORY_LENGTH = 10


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Historique des mouvements : consultation seule (créés uniquement par les services)."""

    list_display = ["created_at", "variant", "delta_display", "reason", "balance_after", "created_by", "note"]
    list_filter = ["reason", "created_at"]
    search_fields = ["variant__sku", "variant__product__name", "variant__product__reference", "note"]
    date_hierarchy = "created_at"
    list_select_related = ["variant__product", "created_by"]
    readonly_fields = ["created_at", "variant", "delta", "reason", "balance_after", "created_by", "note"]
    fields = readonly_fields

    @admin.display(description="variation", ordering="delta")
    def delta_display(self, obj):
        return f"{obj.delta:+d}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # --- Page « Ajuster le stock » ------------------------------------------------

    def get_urls(self):
        adjust = path(
            "adjust/<int:variant_id>/",
            self.admin_site.admin_view(self.adjust_view),
            name="inventory_stock_adjust",
        )
        return [adjust, *super().get_urls()]

    def adjust_view(self, request, variant_id: int):
        if not request.user.has_perm("catalog.change_productvariant"):
            raise PermissionDenied
        variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=variant_id)
        form = StockAdjustmentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                movement = adjust_stock(
                    variant_id=variant.pk, user=request.user, request=request, **form.cleaned_data
                )
            except ValidationError as exc:
                _add_service_errors(form, exc.detail)
            except BusinessError as exc:
                form.add_error(None, exc.message)
            else:
                self.message_user(
                    request,
                    f"Stock de « {variant} » : {movement.delta:+d} → {movement.balance_after}.",
                    messages.SUCCESS,
                )
                return redirect(reverse("admin:catalog_product_change", args=[variant.product_id]))
        context = {
            **self.admin_site.each_context(request),
            "title": f"Ajuster le stock — {variant}",
            "variant": variant,
            "form": form,
            "history": variant.stock_movements.select_related("created_by")[:HISTORY_LENGTH],
            "opts": self.model._meta,
            "product_url": reverse("admin:catalog_product_change", args=[variant.product_id]),
        }
        return TemplateResponse(request, "admin/inventory/stock_adjust.html", context)


def _add_service_errors(form, detail) -> None:
    for field, errors in detail.items() if isinstance(detail, dict) else [(None, detail)]:
        target = field if field in form.fields else None
        for error in errors if isinstance(errors, list) else [errors]:
            form.add_error(target, str(error))


# --- Lien « Ajuster le stock » dans la fiche produit ---------------------------------


class ProductVariantInline(CatalogVariantInline):
    readonly_fields = [*CatalogVariantInline.readonly_fields, "adjust_stock_link"]
    fields = [*CatalogVariantInline.fields, "adjust_stock_link"]

    @admin.display(description="stock")
    def adjust_stock_link(self, obj):
        if not obj.pk:
            return "—"
        url = reverse("admin:inventory_stock_adjust", args=[obj.pk])
        return format_html('<a href="{}">Ajuster le stock</a>', url)


admin.site.unregister(Product)


@admin.register(Product)
class ProductAdmin(CatalogProductAdmin):
    inlines = [ProductVariantInline, *CatalogProductAdmin.inlines[1:]]
