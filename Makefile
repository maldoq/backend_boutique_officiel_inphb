PYTHON ?= python
MANAGE = $(PYTHON) manage.py

.PHONY: run migrate test lint format seed superuser db

run:
	$(MANAGE) runserver 0.0.0.0:8000

migrate:
	$(MANAGE) makemigrations --check
	$(MANAGE) migrate

test:
	pytest --cov=apps --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

seed:
	$(MANAGE) setup_roles
	$(MANAGE) seed_demo

superuser:
	$(MANAGE) createsuperuser

db:
	docker compose up -d db
