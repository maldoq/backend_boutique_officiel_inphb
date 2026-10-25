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
- `SECURE_HSTS_PRELOAD` désactivé par défaut : l'inscription à la liste de préchargement HSTS engage
  durablement le domaine et relève d'une décision de l'INP-HB.
