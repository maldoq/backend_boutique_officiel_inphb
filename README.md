# backend_boutique_officiel_inphb

API Django REST unique de la **Boutique INP-HB** (« FORMER – INNOVER – PRODUIRE »), consommée par le site
public Angular, l'espace d'administration Angular, l'application mobile Flutter et Django Admin (secours).

> Squelette — ce README est complété au fil des étapes (version complète à l'étape 19).

## Stack

Python 3.12+ · Django 5.2 LTS · Django REST Framework · PostgreSQL 16 · JWT (simplejwt) · drf-spectacular

## Démarrage local

Prérequis : Python 3.12 ou plus, Git. PostgreSQL 16 (via Docker Desktop ou installé localement) est la base
cible ; SQLite est accepté pour un démarrage local (voir « Limites connues »).

```bash
cp .env.example .env            # puis renseigner DJANGO_SECRET_KEY (et DATABASE_URL si SQLite)
docker compose up -d db         # PostgreSQL 16 (facultatif si SQLite)
python -m venv .venv
# Windows : .venv\Scripts\activate   —   Linux/macOS : source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Rôles et premier compte administrateur :

```bash
python manage.py setup_roles        # crée les 6 rôles (relançable sans risque)
python manage.py createsuperuser    # premier compte, puis attribuer les rôles dans /django-admin/
```

Les comptes créés depuis Django Admin reçoivent un mot de passe temporaire : toute route métier de
l'admin renvoie `403 password_change_required` tant qu'il n'a pas été changé via
`POST /api/v1/admin/auth/change-password/`.

Journal d'audit : les opérations sensibles (comptes et rôles, paramètres, et à venir prix, stocks,
statuts de commande, boxes, QR) sont tracées dans `AuditLog`, consultable en lecture seule dans
`/django-admin/audit/auditlog/`. Les entrées sont inaltérables et aucune valeur secrète n'y est écrite.

Générer une clé secrète :
`python -c "import secrets; print(secrets.token_urlsafe(50))"`

## Réglages

| Module                  | Usage                                                                  |
|-------------------------|------------------------------------------------------------------------|
| `config.settings.dev`   | développement (défaut de `manage.py`) : DEBUG, e-mails en console      |
| `config.settings.test`  | tests (`pytest`) : fonctionne sans `.env`, throttling désactivé        |
| `config.settings.prod`  | production (défaut de WSGI/ASGI) : HTTPS, HSTS, WhiteNoise, logs JSON |

## URL utiles

- Swagger : <http://localhost:8000/api/docs/> — schéma OpenAPI : <http://localhost:8000/api/schema/>
- Django Admin (secours technique) : <http://localhost:8000/django-admin/>
- API : `http://localhost:8000/api/v1/` (admin métier : `/api/v1/admin/`)
- État du service : <http://localhost:8000/api/v1/health/> — configuration mobile/web :
  <http://localhost:8000/api/v1/app/config/>

## En-têtes HTTP reconnus (web et mobile)

| En-tête             | Rôle                                                                                     |
|---------------------|------------------------------------------------------------------------------------------|
| `X-Visitor-Id`      | identifiant de visite anonyme (UUID v4) ; généré et renvoyé par le serveur s'il manque   |
| `X-Client-Platform` | `web`, `android` ou `ios` (autre valeur : `unknown`)                                     |
| `X-App-Version`     | version de l'application Flutter (ex. `1.2.0`)                                           |
| `Idempotency-Key`   | sur `POST /api/v1/orders/` : évite les commandes en double lors des ré-essais            |

Toutes les erreurs ont la forme `{"error": {"code", "message", "details"}}`.

## Commandes courantes

| Makefile (Linux/macOS) | Équivalent direct (Windows)                                             |
|------------------------|-------------------------------------------------------------------------|
| `make run`             | `python manage.py runserver 0.0.0.0:8000`                               |
| `make migrate`         | `python manage.py makemigrations --check` puis `python manage.py migrate` |
| `make test`            | `pytest --cov=apps --cov-report=term-missing`                           |
| `make lint`            | `ruff check .` puis `ruff format --check .`                             |
| `make superuser`       | `python manage.py createsuperuser`                                      |
| `make db`              | `docker compose up -d db`                                               |

## Limites connues

- **Base SQLite en développement local** (en attendant PostgreSQL) : toléré par la décision D13, mais le
  verrouillage de stock (`select_for_update`) n'est réellement garanti qu'avec PostgreSQL. Les tests de
  concurrence sur le stock devront tourner sur PostgreSQL.
- Paiement en ligne non connecté (décision D05).
- MVP non conforme à une mise en production (D11).
- Déconnexion admin : le refresh est révoqué immédiatement, mais un jeton d'accès déjà émis reste
  valable jusqu'à son expiration (30 min max), fonctionnement normal des JWT. Un changement de mot de
  passe, une désactivation ou un retrait du personnel, eux, invalident aussitôt tous les jetons.
- `SECURE_HSTS_PRELOAD` désactivé par défaut : l'inscription à la liste de préchargement HSTS engage
  durablement le domaine et relève d'une décision de l'INP-HB.
