import json

from django.contrib import admin
from django.utils.html import format_html

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Consultation seule : aucun ajout, aucune modification, aucune suppression (R14)."""

    list_display = ["created_at", "actor_email", "action", "object_type", "object_id", "object_repr"]
    list_filter = ["action", "object_type", "created_at"]
    search_fields = ["actor_email", "action", "object_repr", "object_id"]
    date_hierarchy = "created_at"
    list_select_related = ["actor"]
    fields = [
        "created_at",
        "actor",
        "actor_email",
        "ip_address",
        "action",
        "object_type",
        "object_id",
        "object_repr",
        "changes_display",
    ]
    readonly_fields = fields

    @admin.display(description="modifications")
    def changes_display(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.changes, ensure_ascii=False, indent=2))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
