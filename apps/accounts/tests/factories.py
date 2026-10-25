import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

# Mot de passe des comptes de test uniquement (jamais utilisé hors des tests).
TEST_PASSWORD = "Test-Boutique-2026"


class UserFactory(factory.django.DjangoModelFactory):
    """Membre actif du personnel ; `roles=[...]` lui attribue des groupes de rôles."""

    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"agent{n}@exemple.ci")
    first_name = "Aminata"
    last_name = "Koffi"
    is_staff = True
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", TEST_PASSWORD)

    @factory.post_generation
    def roles(self, create, extracted, **kwargs):
        if create and extracted:
            self.groups.add(*(Group.objects.get_or_create(name=code)[0] for code in extracted))
        if create:
            self.save()
