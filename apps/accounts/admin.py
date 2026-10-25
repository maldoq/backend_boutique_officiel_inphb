"""Django Admin (secours technique) : création des premiers comptes et attribution des rôles."""

from django.contrib import admin
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError

from .capabilities import user_roles
from .models import User


class AdminUserCreationForm(auth_forms.AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Un compte existe déjà avec cette adresse e-mail.")
        return email


class AdminUserChangeForm(auth_forms.UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    ordering = ["email"]
    list_display = ["email", "first_name", "last_name", "roles_display", "is_staff", "is_active"]
    list_filter = ["is_staff", "is_active", "is_superuser", "groups"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    readonly_fields = ["last_login", "date_joined", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "phone")}),
        (
            "Accès",
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "must_change_password"),
                "description": "Les rôles sont les groupes (créés par « python manage.py setup_roles »).",
            },
        ),
        ("Dates", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "last_name", "usable_password", "password1", "password2"),
            },
        ),
    )
    filter_horizontal = ("groups",)

    @admin.display(description="Rôles")
    def roles_display(self, obj):
        return ", ".join(user_roles(obj)) or "—"

    def save_model(self, request, obj, form, change):
        if not change:
            # Compte créé par un administrateur : mot de passe temporaire à changer (E.2).
            obj.is_staff = True
            obj.must_change_password = True
        super().save_model(request, obj, form, change)
