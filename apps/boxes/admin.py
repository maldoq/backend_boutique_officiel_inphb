"""Django Admin des boxes et QR codes : toute écriture passe par les services (validée, auditée).

Le code d'un QR n'est jamais modifiable ; la suppression est désactivée (on désactive, D.4).
"""

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.utils.html import format_html
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import BusinessError

from . import services
from .models import Box, QRCode


def _messages_of(exc) -> list[str]:
    if isinstance(exc, BusinessError):
        return [exc.message]
    detail = exc.detail
    if isinstance(detail, dict):
        return [str(message) for messages_ in detail.values() for message in messages_]
    return [str(message) for message in detail]


@admin.register(Box)
class BoxAdmin(admin.ModelAdmin):
    list_display = ["code", "label", "site", "location_details", "is_active", "active_qr_count"]
    list_filter = ["site", "is_active"]
    search_fields = ["code", "label", "site", "location_details"]
    readonly_fields = ["created_at", "updated_at"]
    actions = ["activate_boxes", "deactivate_boxes"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_active_qr=Count("qr_codes", filter=Q(qr_codes__is_active=True)))
        )

    @admin.display(description="QR actifs", ordering="_active_qr")
    def active_qr_count(self, obj):
        return obj._active_qr

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        data = {name: form.cleaned_data[name] for name in services.BOX_FIELDS if name in form.cleaned_data}
        if change:
            services.update_box(box=Box.objects.get(pk=obj.pk), data=data, user=request.user, request=request)
        else:
            services.create_box(data=data, user=request.user, request=request, instance=obj)

    def _set_active(self, request, queryset, active: bool):
        for box in queryset.filter(is_active=not active):
            services.set_box_active(box=box, active=active, user=request.user, request=request)
        self.message_user(request, "Boxes mises à jour.", messages.SUCCESS)

    @admin.action(description="Activer les boxes sélectionnées", permissions=["change"])
    def activate_boxes(self, request, queryset):
        self._set_active(request, queryset, True)

    @admin.action(
        description="Désactiver les boxes sélectionnées (leurs QR renvoient « QR inactif »)",
        permissions=["change"],
    )
    def deactivate_boxes(self, request, queryset):
        self._set_active(request, queryset, False)


class QRCodeAdminForm(forms.ModelForm):
    class Meta:
        model = QRCode
        fields = ["box", "product", "is_active", "note"]

    def clean(self):
        cleaned = super().clean()
        box, product = cleaned.get("box"), cleaned.get("product")
        if box is None or product is None:
            return cleaned
        existing = self.instance if self.instance.pk else None
        will_be_active = cleaned.get("is_active", True) if existing else True
        if existing and existing.replaced_by_id and will_be_active and not existing.is_active:
            raise forms.ValidationError("Ce QR a été remplacé : utilisez le nouveau code.")
        try:
            services.check_assignment(box, product, exclude=existing, active=will_be_active)
        except (ValidationError, BusinessError) as exc:
            raise forms.ValidationError(_messages_of(exc)) from exc
        return cleaned


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    form = QRCodeAdminForm
    list_display = ["code", "box", "product", "is_active", "scans", "replaced_by", "created_at"]
    list_filter = ["is_active", "box"]
    search_fields = ["code", "box__code", "product__name", "product__reference"]
    list_select_related = ["box", "product", "replaced_by"]
    readonly_fields = [
        "code",
        "public_url_link",
        "replaced_by",
        "activated_at",
        "deactivated_at",
        "created_by",
        "created_at",
        "updated_at",
    ]
    actions = ["deactivate_qr_codes", "activate_qr_codes", "regenerate_qr_codes"]

    def get_fieldsets(self, request, obj=None):
        if obj is None:  # le code est généré : seule la destination se choisit
            return [(None, {"fields": ["box", "product", "note"]})]
        return [
            (None, {"fields": ["code", "public_url_link", "box", "product", "is_active", "note"]}),
            (
                "Historique",
                {
                    "fields": [
                        "replaced_by",
                        "activated_at",
                        "deactivated_at",
                        "created_by",
                        "created_at",
                        "updated_at",
                    ]
                },
            ),
        ]

    def get_queryset(self, request):
        # Relation inverse par son nom : `boxes` n'importe pas `tracking` (C.2).
        return (
            super()
            .get_queryset(request)
            .annotate(_scans=Count("tracking_events", filter=Q(tracking_events__event_type="qr_scan")))
        )

    @admin.display(description="scans", ordering="_scans")
    def scans(self, obj):
        return obj._scans

    @admin.display(description="URL encodée dans le QR")
    def public_url_link(self, obj):
        return format_html('<a href="{0}" target="_blank" rel="noopener">{0}</a>', obj.public_url)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            services.create_qr(
                box=obj.box,
                product=obj.product,
                note=obj.note,
                user=request.user,
                request=request,
                instance=obj,
            )
            return
        current = QRCode.objects.get(pk=obj.pk)
        if {"box", "product"} & set(form.changed_data):
            services.reassign_qr(
                qr=current, box=obj.box, product=obj.product, user=request.user, request=request
            )
        if "is_active" in form.changed_data:
            toggle = services.activate_qr if obj.is_active else services.deactivate_qr
            toggle(qr=current, user=request.user, request=request)
        if "note" in form.changed_data:
            QRCode.objects.filter(pk=obj.pk).update(note=obj.note)

    def _bulk(self, request, queryset, operation, success: str):
        done = 0
        for qr in queryset:
            try:
                operation(qr=qr, user=request.user, request=request)
                done += 1
            except (ValidationError, BusinessError) as exc:
                self.message_user(request, f"{qr.code} : {' '.join(_messages_of(exc))}", messages.ERROR)
        if done:
            self.message_user(request, f"{done} QR code(s) {success}.", messages.SUCCESS)

    @admin.action(description="Désactiver les QR sélectionnés", permissions=["change"])
    def deactivate_qr_codes(self, request, queryset):
        self._bulk(request, queryset, services.deactivate_qr, "désactivé(s)")

    @admin.action(description="Réactiver les QR sélectionnés", permissions=["change"])
    def activate_qr_codes(self, request, queryset):
        self._bulk(request, queryset, services.activate_qr, "réactivé(s)")

    @admin.action(description="Régénérer (nouveau code, l'ancien devient inactif)", permissions=["change"])
    def regenerate_qr_codes(self, request, queryset):
        self._bulk(request, queryset, services.regenerate_qr, "régénéré(s)")
