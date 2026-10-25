"""Routes /api/v1/admin/auth/ : connexion, profil, rotation, déconnexion, mot de passe."""

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import TEST_PASSWORD
from apps.core.throttles import LoginThrottle

LOGIN = "/api/v1/admin/auth/login/"
REFRESH = "/api/v1/admin/auth/refresh/"
LOGOUT = "/api/v1/admin/auth/logout/"
ME = "/api/v1/admin/auth/me/"
CHANGE_PASSWORD = "/api/v1/admin/auth/change-password/"
NEW_PASSWORD = "Nouveau-Secret-2026"


def login(api_client, email, password=TEST_PASSWORD, field="email"):
    return api_client.post(LOGIN, {field: email, "password": password}, format="json")


def bearer(api_client, access):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api_client


def assert_error(response, status, code):
    assert response.status_code == status, response.content
    assert response.json()["error"]["code"] == code


# --- Connexion ---------------------------------------------------------------


@pytest.mark.django_db
def test_login_valide(api_client, make_staff):
    make_staff("RESPONSABLE_BOUTIQUE", email="responsable.boutique@exemple.ci")
    response = login(api_client, "responsable.boutique@exemple.ci")
    assert response.status_code == 200
    data = response.json()
    assert data["access"] and data["refresh"]
    assert data["access_expires_in"] == 1800
    assert data["user"]["email"] == "responsable.boutique@exemple.ci"
    assert data["user"]["roles"] == ["RESPONSABLE_BOUTIQUE"]
    assert "users.manage" not in data["user"]["capabilities"]
    assert len(data["user"]["capabilities"]) == 17
    assert data["user"]["must_change_password"] is False
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_login_met_a_jour_la_derniere_connexion(api_client, make_staff):
    user = make_staff(email="a@exemple.ci")
    assert user.last_login is None
    login(api_client, "a@exemple.ci")
    user.refresh_from_db()
    assert user.last_login is not None


@pytest.mark.django_db
def test_login_insensible_a_la_casse_et_alias_username(api_client, make_staff):
    make_staff(email="agent@exemple.ci")
    assert login(api_client, "  AGENT@Exemple.CI ").status_code == 200
    assert login(api_client, "agent@exemple.ci", field="username").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "case",
    ["mauvais_mot_de_passe", "compte_inexistant", "compte_non_staff", "compte_inactif"],
)
def test_login_refuse_avec_message_generique(api_client, make_staff, case):
    make_staff(email="staff@exemple.ci")
    make_staff(email="client@exemple.ci", is_staff=False)
    make_staff(email="parti@exemple.ci", is_active=False)
    email, password = {
        "mauvais_mot_de_passe": ("staff@exemple.ci", "faux-mot-de-passe"),
        "compte_inexistant": ("inconnu@exemple.ci", TEST_PASSWORD),
        "compte_non_staff": ("client@exemple.ci", TEST_PASSWORD),
        "compte_inactif": ("parti@exemple.ci", TEST_PASSWORD),
    }[case]
    response = login(api_client, email, password)
    assert_error(response, 401, "invalid_credentials")
    assert response.json()["error"]["message"] == "E-mail ou mot de passe incorrect."


@pytest.mark.django_db
def test_login_sans_email_400(api_client):
    response = api_client.post(LOGIN, {"password": "x"}, format="json")
    assert_error(response, 400, "validation_error")
    assert "email" in response.json()["error"]["details"]


@pytest.mark.django_db
def test_login_limite_a_5_tentatives_par_minute(api_client, make_staff, monkeypatch):
    # Le throttling est coupé dans les réglages de test : on rétablit ici le taux réel de « login ».
    monkeypatch.setattr(LoginThrottle, "rate", "5/min", raising=False)
    cache.clear()
    make_staff(email="staff@exemple.ci")
    statuses = [login(api_client, "staff@exemple.ci", "faux").status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    assert_error(login(api_client, "staff@exemple.ci"), 429, "throttled")


# --- Profil ------------------------------------------------------------------


@pytest.mark.django_db
def test_me_sans_jeton_401(api_client):
    assert_error(api_client.get(ME), 401, "not_authenticated")


@pytest.mark.django_db
def test_me_avec_jeton_200(api_client, make_staff):
    make_staff("MARKETING", email="marketing@exemple.ci")
    access = login(api_client, "marketing@exemple.ci").json()["access"]
    response = bearer(api_client, access).get(ME)
    assert response.status_code == 200
    assert response.json()["roles"] == ["MARKETING"]
    assert "boxes.manage" in response.json()["capabilities"]


@pytest.mark.django_db
def test_me_accessible_avec_mot_de_passe_temporaire(api_client, make_staff):
    make_staff(email="nouveau@exemple.ci", must_change_password=True)
    data = login(api_client, "nouveau@exemple.ci").json()
    assert data["user"]["must_change_password"] is True
    response = bearer(api_client, data["access"]).get(ME)
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


# --- Rafraîchissement et déconnexion ----------------------------------------


@pytest.mark.django_db
def test_refresh_rotation_et_ancien_refresh_refuse(api_client, make_staff):
    make_staff(email="staff@exemple.ci")
    first = login(api_client, "staff@exemple.ci").json()
    rotated = api_client.post(REFRESH, {"refresh": first["refresh"]}, format="json")
    assert rotated.status_code == 200
    assert rotated.json()["refresh"] != first["refresh"]
    assert rotated.json()["access_expires_in"] == 1800
    assert_error(
        api_client.post(REFRESH, {"refresh": first["refresh"]}, format="json"), 401, "authentication_failed"
    )
    assert api_client.post(REFRESH, {"refresh": rotated.json()["refresh"]}, format="json").status_code == 200


@pytest.mark.django_db
def test_logout_puis_refresh_401(api_client, make_staff):
    make_staff(email="staff@exemple.ci")
    refresh = login(api_client, "staff@exemple.ci").json()["refresh"]
    assert api_client.post(LOGOUT, {"refresh": refresh}, format="json").status_code == 204
    assert_error(api_client.post(REFRESH, {"refresh": refresh}, format="json"), 401, "authentication_failed")


@pytest.mark.django_db
def test_logout_jeton_invalide_401(api_client):
    assert_error(
        api_client.post(LOGOUT, {"refresh": "pas-un-jeton"}, format="json"), 401, "authentication_failed"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["desactive", "retire_du_personnel", "supprime"])
def test_refresh_refuse_si_le_compte_change(api_client, make_staff, change):
    user = make_staff(email="staff@exemple.ci")
    refresh = login(api_client, "staff@exemple.ci").json()["refresh"]
    if change == "supprime":
        user.delete()
    else:
        setattr(user, "is_active" if change == "desactive" else "is_staff", False)
        user.save()
    assert_error(api_client.post(REFRESH, {"refresh": refresh}, format="json"), 401, "authentication_failed")


# --- Changement de mot de passe ----------------------------------------------


@pytest.mark.django_db
def test_changement_de_mot_de_passe_ferme_toutes_les_sessions(api_client, make_staff):
    user = make_staff("ADMIN_GENERAL", email="admin@exemple.ci", must_change_password=True)
    old = login(api_client, "admin@exemple.ci").json()
    other_session = login(api_client, "admin@exemple.ci").json()

    response = bearer(api_client, old["access"]).post(
        CHANGE_PASSWORD, {"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    new = response.json()
    assert new["user"]["must_change_password"] is False
    user.refresh_from_db()
    assert user.must_change_password is False and user.check_password(NEW_PASSWORD)

    # Anciens jetons (accès et refresh, des deux sessions) immédiatement invalides.
    assert bearer(api_client, old["access"]).get(ME).status_code == 401
    for refresh in (old["refresh"], other_session["refresh"]):
        assert api_client.post(REFRESH, {"refresh": refresh}, format="json").status_code == 401
    # Nouveaux jetons valides ; ancien mot de passe refusé.
    assert bearer(api_client, new["access"]).get(ME).status_code == 200
    api_client.credentials()
    assert login(api_client, "admin@exemple.ci").status_code == 401
    assert login(api_client, "admin@exemple.ci", NEW_PASSWORD).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("current", "new", "field"),
    [
        ("faux-mot-de-passe", NEW_PASSWORD, "current_password"),
        (TEST_PASSWORD, "court", "new_password"),
        (TEST_PASSWORD, "1234567890123", "new_password"),
        (TEST_PASSWORD, TEST_PASSWORD, "new_password"),
    ],
)
def test_changement_de_mot_de_passe_refuse(admin_api_client, current, new, field):
    client = admin_api_client("ADMIN_GENERAL")
    response = client.post(CHANGE_PASSWORD, {"current_password": current, "new_password": new}, format="json")
    assert_error(response, 400, "validation_error")
    assert field in response.json()["error"]["details"]
    client.user.refresh_from_db()
    assert client.user.check_password(TEST_PASSWORD)


@pytest.mark.django_db
def test_changement_de_mot_de_passe_sans_jeton_401(api_client):
    response = api_client.post(CHANGE_PASSWORD, {"current_password": "a", "new_password": "b"}, format="json")
    assert_error(response, 401, "not_authenticated")


@pytest.mark.django_db
def test_routes_auth_documentees(api_client):
    schema = api_client.get("/api/schema/").content.decode()
    for path in (LOGIN, REFRESH, LOGOUT, ME, CHANGE_PASSWORD):
        assert path in schema
