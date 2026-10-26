from django.contrib import admin

from .models import TrackingEvent


@admin.register(TrackingEvent)
class TrackingEventAdmin(admin.ModelAdmin):
    """Consultation seule. Purge par la commande de rétention, jamais à la main."""

    list_display = ["occurred_at", "event_type", "channel", "box", "qr", "product", "visitor_short"]
    list_filter = ["event_type", "channel", "box", "occurred_at"]
    search_fields = ["qr__code", "box__code", "product__name"]
    date_hierarchy = "occurred_at"
    list_select_related = ["box", "qr", "product"]

    @admin.display(description="visiteur")
    def visitor_short(self, obj):
        return str(obj.visitor_id)[:8]  # identifiant anonyme, tronqué à l'affichage

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
