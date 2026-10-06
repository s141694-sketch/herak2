# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1
WORKDIR /app
# LibreOffice Writer and Arabic fonts make the PDF of an approved program from its Word file (D78).
# pg_dump and pg_restore must match the server's major version (PostgreSQL 18) for backups (D83): from
# PostgreSQL's own repository, as its download page describes.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libpq5 libreoffice-writer-nogui fonts-noto-core \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSo /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
ENV PATH="/opt/venv/bin:$PATH" DJANGO_SETTINGS_MODULE=config.settings.production
RUN DJANGO_SETTINGS_MODULE=config.settings.test SECRET_KEY=build DATABASE_URL=postgres://x:x@localhost/x REDIS_URL=redis://localhost/0 python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
