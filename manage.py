#!/usr/bin/env python
"""Utilitaire de ligne de commande Django."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django est introuvable. L'environnement virtuel est-il activé ?\n"
            "  Windows : .venv\\Scripts\\activate   (ou .venv\\Scripts\\python.exe manage.py …)\n"
            "  Linux/macOS : source .venv/bin/activate\n"
            "Sinon, installez les dépendances : pip install -r requirements/dev.txt"
        ) from exc
    check_settings()
    execute_from_command_line(sys.argv)


def check_settings():
    """Charge les réglages tout de suite pour afficher la vraie cause d'un échec.

    Sinon Django masque l'erreur et échoue plus loin sur « Models aren't loaded yet » (AppRegistryNotReady).
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    try:
        settings.INSTALLED_APPS  # noqa: B018 (déclenche le chargement des réglages)
    except ImproperlyConfigured as exc:
        sys.exit(
            f"Configuration invalide : {exc}\n"
            "Le fichier .env existe-t-il à la racine du projet ? Créez-le depuis le modèle et complétez-le\n"
            "(DJANGO_SECRET_KEY, et DATABASE_URL=sqlite:///db.sqlite3 sans PostgreSQL) :\n"
            "  Windows : copy .env.example .env\n"
            "  Linux/macOS : cp .env.example .env"
        )
    except ImportError as exc:
        sys.exit(
            f"Module introuvable au chargement des réglages : {exc}\n"
            "Installez les dépendances dans l'environnement virtuel : pip install -r requirements/dev.txt"
        )


if __name__ == "__main__":
    main()
