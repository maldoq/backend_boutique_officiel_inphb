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
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
