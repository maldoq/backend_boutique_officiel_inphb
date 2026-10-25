# backend_boutique_officiel_inphb

API Django REST unique de la **Boutique INP-HB** (« FORMER – INNOVER – PRODUIRE »), consommée par le site
public Angular, l'espace d'administration Angular, l'application mobile Flutter et Django Admin (secours).

> Squelette — ce README est complété au fil des étapes (version complète à l'étape 19).

## Stack

Python 3.12+ · Django 5.2 LTS · Django REST Framework · PostgreSQL 16 · JWT (simplejwt) · drf-spectacular

## Démarrage local

Prérequis : Python 3.12 ou plus, Git, Docker Desktop (ou un PostgreSQL 16 installé localement).

```bash
cp .env.example .env            # puis renseigner DJANGO_SECRET_KEY
docker compose up -d db         # PostgreSQL 16
python -m venv .venv
# Windows : .venv\Scripts\activate   —   Linux/macOS : source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py check
```

## Raccourcis (Makefile)

`make run` · `make migrate` · `make test` · `make lint` · `make seed` · `make superuser` · `make db`

## Limites connues

- Paiement en ligne non connecté (décision D05).
- MVP non conforme à une mise en production (D11).
