from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.capabilities import sort_capabilities, user_capabilities, user_roles


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    username = serializers.CharField(
        required=False, help_text="Alias de « email » (compatibilité avec le contrat initial)."
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get("email") or attrs.get("username")
        if not email:
            raise serializers.ValidationError({"email": ["Ce champ est obligatoire."]})
        return {"email": email.strip(), "password": attrs["password"]}


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)


class AdminProfileSerializer(serializers.ModelSerializer):
    """Profil du membre du personnel connecté, avec ses rôles et capacités (affichage des menus)."""

    roles = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "roles",
            "capabilities",
            "is_superuser",
            "must_change_password",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_roles(self, user):
        return user_roles(user)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_capabilities(self, user):
        return sort_capabilities(user_capabilities(user))


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    access_expires_in = serializers.IntegerField(help_text="Durée de validité du jeton d'accès (s).")


class SessionSerializer(TokenPairSerializer):
    user = AdminProfileSerializer()
