"""Django Admin (secours technique) : création des premiers comptes et attribution des rôles."""

from django.contrib import admin
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.core.signals import emit_sensitive_change

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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        if not change:
            changes = {name: [None, getattr(user, name)] for name in AUDITED_CREATE_FIELDS}
            self._audit(request, user, "user.create", changes)
            return
        # Valeurs réellement enregistrées (e-mail en minuscules, etc.), champs inchangés ignorés.
        changes = {
            name: [form.initial.get(name), getattr(user, name)]
            for name in form.changed_data
            if name in AUDITED_UPDATE_FIELDS and form.initial.get(name) != getattr(user, name)
        }
        if changes:
            self._audit(request, user, "user.update", changes)
        if "groups" in form.changed_data:
            before = _group_names(form.initial.get("groups") or [])
            after = _group_names(form.cleaned_data.get("groups") or [])
            if before != after:
                self._audit(request, user, "user.role_change", {"roles": [before, after]})

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:  # formulaire valide, enregistré
            user = self.get_object(request, id)
            if user.pk != request.user.pk and user.has_usable_password():
                # Mot de passe défini par un administrateur : temporaire, à changer à la connexion.
                user.must_change_password = True
                user.save(update_fields=["must_change_password", "updated_at"])
            self._audit(
                request,
                user,
                "user.password_reset",
                {"must_change_password": [None, user.must_change_password]},
            )
        return response

    @staticmethod
    def _audit(request, user, action, changes):
        emit_sensitive_change(
            sender=User, actor=request.user, action=action, obj=user, changes=changes, request=request
        )


AUDITED_CREATE_FIELDS = ("email", "first_name", "last_name", "is_staff", "must_change_password")
AUDITED_UPDATE_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "phone",
    "is_active",
    "is_staff",
    "is_superuser",
    "must_change_password",
)


def _group_names(groups) -> list[str]:
    """Noms triés, que `groups` contienne des objets Group ou des identifiants."""
    ids = [getattr(group, "pk", group) for group in groups]
    return sorted(Group.objects.filter(pk__in=ids).values_list("name", flat=True))
