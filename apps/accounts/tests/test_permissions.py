"""HasCapability : 401 sans jeton, 403 sans capacité, 2xx avec (matrice complète 6 rôles × 18 capacités).

Les routes métier n'existent pas encore à l'étape 3 : la matrice est vérifiée sur des vues de test ;
chaque étape suivante teste ensuite ses propres routes.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.capabilities import ALL_CAPABILITIES, ROLE_CAPABILITIES, ROLES, admin_caps
from apps.accounts.tokens import issue_tokens
from apps.accounts.viewsets import AdminAPIView

factory = APIRequestFactory()


def view_requiring(capability):
    class CapabilityView(AdminAPIView):
        required_capabilities = {"*": capability}

        def get(self, request):
            return Response({"ok": True})

    return CapabilityView.as_view()


def call(view, user=None, method="get", token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    request = getattr(factory, method)("/api/v1/admin/test/", **headers)
    if user is not None:
        force_authenticate(request, user=user)
    return view(request)


@pytest.mark.django_db
@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize("capability", ALL_CAPABILITIES)
def test_matrice_par_role_et_capacite(make_staff, role, capability):
    response = call(view_requiring(capability), user=make_staff(role))
    expected = 200 if capability in ROLE_CAPABILITIES[role] else 403
    assert response.status_code == expected


@pytest.mark.django_db
def test_anonyme_401():
    response = call(view_requiring("catalog.view"))
    assert response.status_code == 401
    assert response.data["error"]["code"] == "not_authenticated"


@pytest.mark.django_db
def test_jeton_invalide_401():
    response = call(view_requiring("catalog.view"), token="pas.un.jeton")
    assert response.status_code == 401
    assert response.data["error"]["code"] == "authentication_failed"


@pytest.mark.django_db
def test_vrai_jeton_jwt_accepte(make_staff):
    user = make_staff("ADMIN_GENERAL")
    response = call(view_requiring("catalog.view"), token=issue_tokens(user)["access"])
    assert response.status_code == 200


@pytest.mark.django_db
def test_compte_non_staff_403_meme_avec_tous_les_groupes(make_staff):
    client_account = make_staff("ADMIN_GENERAL", is_staff=False)  # futur compte client (Phase 2)
    response = call(view_requiring("catalog.view"), user=client_account)
    assert response.status_code == 403


@pytest.mark.django_db
def test_compte_desactive_apres_emission_du_jeton_401(make_staff):
    user = make_staff("ADMIN_GENERAL")
    token = issue_tokens(user)["access"]
    user.is_active = False
    user.save()
    assert call(view_requiring("catalog.view"), token=token).status_code == 401


@pytest.mark.django_db
def test_mot_de_passe_temporaire_bloque_les_routes_metier(make_staff):
    user = make_staff("ADMIN_GENERAL", must_change_password=True)
    response = call(view_requiring("catalog.view"), user=user)
    assert response.status_code == 403
    assert response.data["error"]["code"] == "password_change_required"


@pytest.mark.django_db
def test_capacite_par_methode_http(make_staff):
    class CatalogView(AdminAPIView):
        required_capabilities = admin_caps("catalog.view", "catalog.manage")

        def get(self, request):
            return Response({})

        def post(self, request):
            return Response({}, status=201)

    view = CatalogView.as_view()
    reader = make_staff("GESTIONNAIRE_COMMANDES")  # catalog.view sans catalog.manage
    assert call(view, user=reader).status_code == 200
    assert call(view, user=reader, method="post").status_code == 403
    assert call(view, user=make_staff("GESTIONNAIRE_CATALOGUE"), method="post").status_code == 201


@pytest.mark.django_db
def test_vue_sans_capacite_declaree_refusee(make_staff):
    class ForgottenView(AdminAPIView):
        def get(self, request):
            return Response({})

    with pytest.raises(ImproperlyConfigured):
        call(ForgottenView.as_view(), user=make_staff("ADMIN_GENERAL"))
