from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Ligne unique : la liste redirige vers le formulaire ; ni ajout ni suppression."""

    fieldsets = [
        ("Boutique", {"fields": ["shop_name", "slogan", "contact_phone", "contact_email"]}),
        (
            "Commandes et stock",
            {
                "fields": ["default_low_stock_threshold", "pickup_hold_days", "order_confirmation_message"],
            },
        ),
        ("Exploitation", {"fields": ["maintenance_mode"]}),
        ("Suivi", {"fields": ["created_at", "updated_at"]}),
    ]
    readonly_fields = ["created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        site = SiteSettings.load()
        return redirect(reverse("admin:core_sitesettings_change", args=[site.pk]))
