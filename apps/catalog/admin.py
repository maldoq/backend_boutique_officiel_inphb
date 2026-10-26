"""Django Admin du catalogue (secours technique). Écritures sensibles auditées (R14).

Le stock y est en lecture seule : il ne change que par les services de stock (apps.inventory),
qui ajoutent leur propre action d'ajustement à cet admin (étape 7).
"""

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from apps.audit.services import log_action

from .models import Category, Product, ProductImage, ProductVariant

PRICE_FIELDS = {"price_xof", "compare_at_price_xof"}


def _changes(previous, current, fields) -> dict:
    return {
        name: [getattr(previous, name), getattr(current, name)]
        for name in fields
        if getattr(previous, name) != getattr(current, name)
    }


def _audit_update(request, obj, changes: dict, *, domain: str) -> None:
    """Prix dans une entrée « <domaine>.price_change », le reste dans « <domaine>.update »."""
    price_changes = {name: pair for name, pair in changes.items() if name in PRICE_FIELDS}
    other_changes = {name: pair for name, pair in changes.items() if name not in PRICE_FIELDS}
    if price_changes:
        log_action(
            actor=request.user,
            action=f"{domain}.price_change",
            obj=obj,
            changes=price_changes,
            request=request,
        )
    if other_changes:
        log_action(
            actor=request.user, action=f"{domain}.update", obj=obj, changes=other_changes, request=request
        )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "slug", "position", "is_active", "product_count"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    list_editable = ["position", "is_active"]
    readonly_fields = ["created_at", "updated_at"]

    def get_queryset(self, request):
        return (
            super().get_queryset(request).select_related("parent").annotate(_product_count=Count("products"))
        )

    @admin.display(description="produits", ordering="_product_count")
    def product_count(self, obj):
        return obj._product_count

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":  # un seul niveau : seules les catégories racines sont parentes
            kwargs["queryset"] = Category.objects.filter(parent__isnull=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ProductVariantInlineFormSet(forms.BaseInlineFormSet):
    """La variante obligatoire est enregistrée même laissée telle quelle : elle devient « Standard »."""

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if i < self.min_num and form.instance.pk is None:
            form.empty_permitted = False
            form.has_changed = lambda: True
        return form

    def clean(self):
        # Django Admin ne transmet pas validate_min : la règle « au moins une variante » est imposée ici.
        super().clean()
        kept = [
            form
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE")
            and (form.instance.pk or form.has_changed())
        ]
        if not kept:
            raise forms.ValidationError("Un produit doit avoir au moins une variante.")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    formset = ProductVariantInlineFormSet
    fields = [
        "size",
        "color",
        "model",
        "sku",
        "label",
        "price_xof",
        "stock_quantity",
        "low_stock_threshold",
        "is_active",
        "position",
    ]
    readonly_fields = ["label", "stock_quantity"]
    extra = 0
    min_num = 1  # un produit a toujours au moins une variante
    validate_min = True
    can_delete = False  # désactiver (is_active) plutôt que supprimer : historique des commandes


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    fields = ["preview", "image", "alt_text", "position", "is_main"]
    readonly_fields = ["preview"]
    extra = 0

    @admin.display(description="aperçu")
    def preview(self, obj):
        if obj.pk and obj.thumbnail:
            return format_html('<img src="{}" alt="" style="height:60px">', obj.thumbnail.url)
        return "—"


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "reference",
            "name",
            "slug",
            "category",
            "short_description",
            "description",
            "price_xof",
            "compare_at_price_xof",
            "is_active",
            "is_featured",
            "is_coming_soon",
            "related_products",
            "seo_title",
            "seo_description",
        ]

    def clean_related_products(self):
        related = self.cleaned_data["related_products"]
        if self.instance.pk and related.filter(pk=self.instance.pk).exists():
            raise forms.ValidationError("Un produit ne peut pas être associé à lui-même.")
        return related


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    inlines = [ProductVariantInline, ProductImageInline]
    list_display = [
        "reference",
        "name",
        "category",
        "price_xof",
        "availability_display",
        "is_active",
        "is_featured",
    ]
    list_filter = ["is_active", "is_featured", "is_coming_soon", "category"]
    search_fields = ["reference", "name", "slug", "variants__sku"]
    list_select_related = ["category"]
    filter_horizontal = ["related_products"]
    readonly_fields = ["created_by", "created_at", "updated_at"]
    actions = ["activate_products", "deactivate_products"]
    fieldsets = [
        (None, {"fields": ["reference", "name", "slug", "category"]}),
        ("Descriptions", {"fields": ["short_description", "description"]}),
        ("Prix (XOF)", {"fields": ["price_xof", "compare_at_price_xof"]}),
        ("Publication", {"fields": ["is_active", "is_featured", "is_coming_soon", "related_products"]}),
        ("Référencement", {"fields": ["seo_title", "seo_description"], "classes": ["collapse"]}),
        ("Suivi", {"fields": ["created_by", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("variants").distinct()

    @admin.display(description="disponibilité")
    def availability_display(self, obj):
        return obj.availability_label

    def has_delete_permission(self, request, obj=None):
        return False  # désactiver plutôt que supprimer (D.4)

    # --- Audit des écritures ---------------------------------------------------

    def save_model(self, request, obj, form, change):
        previous = Product.objects.get(pk=obj.pk) if change else None
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        if not change:
            log_action(
                actor=request.user,
                action="product.create",
                obj=obj,
                changes={
                    name: [None, getattr(obj, name)]
                    for name in (
                        "reference",
                        "name",
                        "category",
                        "price_xof",
                        "compare_at_price_xof",
                        "is_active",
                    )
                },
                request=request,
            )
        else:
            fields = [name for name in form.changed_data if name != "related_products"]
            _audit_update(request, obj, _changes(previous, obj, fields), domain="product")

    def save_formset(self, request, form, formset, change):
        if formset.model is not ProductVariant:
            return super().save_formset(request, form, formset, change)
        edited = [f.instance.pk for f in formset.forms if f.instance.pk and f.has_changed()]
        previous = ProductVariant.objects.in_bulk(edited)
        super().save_formset(request, form, formset, change)
        for variant in formset.new_objects:
            log_action(
                actor=request.user,
                action="variant.create",
                obj=variant,
                changes={
                    name: [None, getattr(variant, name)]
                    for name in ("sku", "label", "price_xof", "is_active")
                },
                request=request,
            )
        for variant, changed_fields in formset.changed_objects:
            _audit_update(
                request, variant, _changes(previous[variant.pk], variant, changed_fields), domain="variant"
            )

    # --- Actions groupées --------------------------------------------------------

    def _set_active(self, request, queryset, active: bool):
        updated = 0
        for product in queryset.filter(is_active=not active):
            product.is_active = active
            product.save(update_fields=["is_active", "updated_at"])
            log_action(
                actor=request.user,
                action="product.update",
                obj=product,
                changes={"is_active": [not active, active]},
                request=request,
            )
            updated += 1
        self.message_user(
            request, f"{updated} produit(s) {'activé' if active else 'désactivé'}(s).", messages.SUCCESS
        )

    @admin.action(description="Activer les produits sélectionnés", permissions=["change"])
    def activate_products(self, request, queryset):
        self._set_active(request, queryset, True)

    @admin.action(description="Désactiver les produits sélectionnés", permissions=["change"])
    def deactivate_products(self, request, queryset):
        self._set_active(request, queryset, False)
