"""Django Admin des commandes (secours technique).

Commandes en LECTURE SEULE : les changements de statut passent par les services de l'étape 14
(transitions contrôlées, historique, audit), jamais par une modification directe du champ.
"""

from django.contrib import admin

from apps.audit.services import diff_instance, log_action

from .models import Order, OrderItem, OrderStatusHistory, PickupPoint

PICKUP_FIELDS = ("code", "name", "address", "instructions", "opening_hours", "phone", "is_active", "position")


@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "address", "opening_hours", "is_active", "position"]
    list_filter = ["is_active"]
    search_fields = ["name", "code", "address"]
    readonly_fields = ["created_at", "updated_at"]

    def has_delete_permission(self, request, obj=None):
        return False  # désactiver plutôt que supprimer (commandes rattachées)

    def save_model(self, request, obj, form, change):
        changes = (
            diff_instance(PickupPoint.objects.get(pk=obj.pk), form.cleaned_data, PICKUP_FIELDS)
            if change
            else {name: [None, form.cleaned_data.get(name)] for name in ("code", "name", "is_active")}
        )
        super().save_model(request, obj, form, change)
        if changes:
            log_action(
                actor=request.user,
                action="pickup_point.update" if change else "pickup_point.create",
                obj=obj,
                changes=changes,
                request=request,
            )


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyInline):
    model = OrderItem
    fields = [
        "product_name",
        "variant_label",
        "sku",
        "unit_price_xof",
        "quantity",
        "line_total_xof",
        "source_box",
        "source_qr",
    ]
    readonly_fields = fields


class OrderStatusHistoryInline(ReadOnlyInline):
    model = OrderStatusHistory
    fields = ["created_at", "from_status", "to_status", "changed_by", "note"]
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "public_reference",
        "created_at",
        "customer_last_name",
        "customer_first_name",
        "customer_phone",
        "status",
        "payment_status",
        "total_xof",
        "pickup_point",
        "channel",
    ]
    list_filter = ["status", "payment_status", "pickup_point", "channel", "created_at"]
    search_fields = [
        "public_reference",
        "customer_last_name",
        "customer_first_name",
        "customer_phone",
        "pickup_code",
    ]
    date_hierarchy = "created_at"
    list_select_related = ["pickup_point"]
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    fieldsets = [
        (
            "Commande",
            {
                "fields": [
                    "public_reference",
                    "status",
                    "payment_status",
                    "fulfillment_method",
                    "pickup_point",
                    "pickup_code",
                    "channel",
                    "created_at",
                ]
            },
        ),
        (
            "Client",
            {
                "fields": [
                    "customer_first_name",
                    "customer_last_name",
                    "customer_phone",
                    "customer_email",
                    "customer_note",
                    "accepted_terms_at",
                ]
            },
        ),
        (
            "Montants (XOF)",
            {"fields": ["subtotal_xof", "discount_xof", "shipping_fee_xof", "total_xof", "currency"]},
        ),
        ("Attribution", {"fields": ["source_box", "source_qr"]}),
        (
            "Suivi",
            {
                "fields": [
                    "ready_at",
                    "collected_at",
                    "collected_by",
                    "cancelled_at",
                    "cancelled_by",
                    "cancellation_reason",
                    "internal_note",
                ]
            },
        ),
    ]

    def get_readonly_fields(self, request, obj=None):
        return [field for fieldset in self.fieldsets for field in fieldset[1]["fields"]]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
