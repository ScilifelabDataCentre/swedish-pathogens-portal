# Getting started

Set up `spp-wagtail` on your machine. All commands assume you are in the **repository root**.

Choose **one** run path:

| Path | Guide |
|------|--------|
| Docker (recommended) | [Docker development](docker-development.md) |
| Python on host with uv | [Local development (uv)](local-development.md) |

---

## Prerequisites

- **git**
- **Docker path:** Docker and Docker Compose
- **uv path:** Python ≥ 3.14, [uv](https://docs.astral.sh/uv/), and a reachable PostgreSQL instance (see [local guide](local-development.md))

---

## Environment file (`.env`)

Create `.env` before either path:

```bash
cp .env.example .env
```

Django reads this file on startup (`core/settings/base.py`). The `web` service in `compose.yaml` also loads it and builds `DATABASE_URL` for containers.

### Create `SECRET_KEY` and add it to `.env`

`SECRET_KEY` is **required**. The app will not start if `.env.example` placeholders are left unchanged.

**1. Generate a key** (from the repo root):

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the printed string (one line, no quotes).

**2. Open `.env`** and replace the placeholder:

```env
# Before (from .env.example — will not work)
SECRET_KEY=<required>

# After — paste your generated value
SECRET_KEY=django-insecure-abc123...your-actual-key-here
```

Do not commit `.env` or share the key; each developer uses their own local value.

### Other required database variables

| Variable | Typical local value |
|----------|---------------------|
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | `password` |
| `POSTGRES_DB` | `postgres` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_HOST` | `db` (Docker) or `localhost` (uv on host) |
| `DATABASE_URL` | Set by Compose for Docker; **you must add** for uv (see examples below) |

### Final `.env` example — Docker (recommended)

Use this shape when you run `docker compose up`. Compose injects `DATABASE_URL` for the `web` container — you do not add it yourself.

```env
# Django — required
SECRET_KEY=paste-your-generated-secret-key-here

# Production-only in .env.example — safe to leave as placeholders for local dev
ADMIN_URL=<required-for-production>
MEDIA_ROOT=<required-for-production>
ALLOWED_HOSTS=<required-for-production>
CSRF_TRUSTED_ORIGINS=<required-for-production>

# Database — host must be "db" (Docker service name)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=postgres

# Security / Gunicorn — defaults from .env.example are fine locally
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
GUNICORN_WORKERS=2
GUNICORN_THREADS=4

# Optional Docker build
with_pygraphviz=false
```

Then follow [Docker development](docker-development.md).

### Final `.env` example — uv on host

Use this shape when you run `uv run python manage.py runserver`. You must set `DATABASE_URL` and use `localhost` for the database host.

```env
# Django — required
SECRET_KEY=paste-your-generated-secret-key-here

# Production-only — placeholders OK for core.settings.development
ADMIN_URL=<required-for-production>
MEDIA_ROOT=<required-for-production>
ALLOWED_HOSTS=<required-for-production>
CSRF_TRUSTED_ORIGINS=<required-for-production>

# Database — host must be reachable from your machine (usually localhost)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=postgres

# Required for uv — must match user, password, host, port, db above
DATABASE_URL=psql://postgres:password@localhost:5432/postgres

SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
GUNICORN_WORKERS=2
GUNICORN_THREADS=4

with_pygraphviz=false
```

Postgres must listen on `localhost:5432`. Default `compose.yaml` does not publish the DB port — see [local development](local-development.md).

### Checklist if something fails

1. `.env` exists in the repo root (same folder as `manage.py`).
2. `SECRET_KEY` is set and non-empty.
3. **Docker:** `POSTGRES_HOST=db`; run `docker compose up` (not only `db` if you need the app).
4. **uv:** `DATABASE_URL` uses `localhost` (or your host); Postgres is running and reachable.
5. After pulling model changes: run migrations (see your path’s guide).

---

## Optional: pre-commit

Ruff lint and format:

```bash
uv sync --group dev
uv run pre-commit install
uv run pre-commit run --all-files
```

CI uses the same checks — `.github/workflows/ruff.yaml`.

---

## Next steps

- [Docker development](docker-development.md)
- [Local development (uv)](local-development.md)
- [Developer guide index](README.md)
