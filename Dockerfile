FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt

COPY . .
# collectstatic avec des valeurs factices (aucun secret dans l'image)
RUN DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=build DATABASE_URL=sqlite:///tmp.db \
    DJANGO_ALLOWED_HOSTS=localhost PUBLIC_WEB_BASE_URL=http://x API_PUBLIC_BASE_URL=http://x \
    python manage.py collectstatic --noinput

RUN useradd -m app && chown -R app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
