from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import SiteSettings
from .signals import emit_sensitive_change


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

    def save_model(self, request, obj, form, change):
        previous = SiteSettings.load()
        super().save_model(request, obj, form, change)
        # Valeurs réellement enregistrées (après normalisation), champs inchangés ignorés.
        changes = {
            name: [getattr(previous, name), getattr(obj, name)]
            for name in form.changed_data
            if getattr(previous, name) != getattr(obj, name)
        }
        if changes:
            emit_sensitive_change(
                sender=SiteSettings,
                actor=request.user,
                action="settings.update",
                obj=obj,
                changes=changes,
                request=request,
            )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        site = SiteSettings.load()
        return redirect(reverse("admin:core_sitesettings_change", args=[site.pk]))
