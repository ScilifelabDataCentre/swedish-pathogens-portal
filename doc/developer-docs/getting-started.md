# Getting started

Set up the **Swedish Pathogens Portal** repository on your machine. All commands assume you are in the **repository root**.

Choose **one** run path:

| Path | Guide |
|------|--------|
| Docker (recommended) | [Docker deployment](docker-deployment.md) |
| Python on host with uv | [Local deployment (uv)](local-deployment.md) |

---

## Prerequisites

- **git**
- **Docker path:** Docker and Docker Compose
- **uv path:** Python ≥ 3.14, [uv](https://docs.astral.sh/uv/), and a reachable PostgreSQL instance (see [local deployment](local-deployment.md))

---

## Environment file (`.env`)

Create `.env` before either path:

```bash
cp .env.example .env
```

Django reads this file on startup (`core/settings/base.py`). The `web` service in `compose.yaml` also loads it and builds `DATABASE_URL` for containers. Keep `.env.example` as the source of truth for new variables.

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

### Database variables

Defaults below match `.env.example` (Compose Postgres service).

| Variable | Typical local value |
|----------|---------------------|
| `POSTGRES_USER` | `app` |
| `POSTGRES_PASSWORD` | `password` |
| `POSTGRES_DB` | `spp` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_HOST` | `db` (Docker) or `localhost` (uv on host) |
| `DATABASE_URL` | Set by Compose for Docker; **you must add** for uv (see examples below) |

### Production-oriented placeholders

These appear in `.env.example`. For local development with `core.settings.development` you can leave the placeholder values:

| Variable | Notes |
|----------|--------|
| `MEDIA_ROOT` | Required in production |
| `ALLOWED_HOSTS` | Required in production |
| `CSRF_TRUSTED_ORIGINS` | Required in production |
| `WAGTAILADMIN_URL` / `WAGTAILADMIN_BASE_URL` | Required in production |
| `DJANGO_ADMIN_URL` | Only if `INCLUDE_DJANGO_ADMIN` is enabled |
| `DATASETS_ROOT` | Optional; portal data study dirs — see [Portal Data](portal_data.md) |

### Final `.env` example — Docker (recommended)

Use this shape when you run `docker compose up`. Compose injects `DATABASE_URL` for the `web` container — you do not add it yourself.

```env
# Django — required
SECRET_KEY=paste-your-generated-secret-key-here

# Production-only in .env.example — safe to leave as placeholders for local dev
MEDIA_ROOT=<required-for-production>
ALLOWED_HOSTS=<required-for-production>
CSRF_TRUSTED_ORIGINS=<required-for-production>
WAGTAILADMIN_URL=<required-for-production>
WAGTAILADMIN_BASE_URL=<required-for-production>

# Database — host must be "db" (Docker service name)
POSTGRES_USER=app
POSTGRES_PASSWORD=password
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=spp

# Security / Gunicorn — defaults from .env.example are fine locally
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
GUNICORN_WORKERS=2
GUNICORN_THREADS=4

# Optional Docker build
with_pygraphviz=false
```

Then follow [Docker deployment](docker-deployment.md).

### Final `.env` example — uv on host

Use this shape when you run `uv run python manage.py runserver`. You must set `DATABASE_URL` and use `localhost` for the database host.

```env
# Django — required
SECRET_KEY=paste-your-generated-secret-key-here

# Production-only — placeholders OK for core.settings.development
MEDIA_ROOT=<required-for-production>
ALLOWED_HOSTS=<required-for-production>
CSRF_TRUSTED_ORIGINS=<required-for-production>
WAGTAILADMIN_URL=<required-for-production>
WAGTAILADMIN_BASE_URL=<required-for-production>

# Database — host must be reachable from your machine (usually localhost)
POSTGRES_USER=app
POSTGRES_PASSWORD=password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=spp

# Required for uv — must match user, password, host, port, db above
DATABASE_URL=psql://app:password@localhost:5432/spp

SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
GUNICORN_WORKERS=2
GUNICORN_THREADS=4

with_pygraphviz=false
```

Postgres must listen on `localhost:5432`. Default `compose.yaml` does not publish the DB port — see [local deployment](local-deployment.md).

### Email (local and production)

Contact form and other mail use Django’s mailers (`core/settings/development.py` / `production.py`). Variables are documented in `.env.example`.

| Context | What to set |
|---------|-------------|
| **Local Docker** | Optional Mailpit: `docker compose --profile mailpit up` — UI at http://localhost:8025 ; Compose sets `EMAIL_HOST=mailpit` on `web` |
| **Local without SMTP** | `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` prints mail to the process log |
| **Production** | `DEFAULT_FROM_EMAIL` (must be an `@scilifelab.se` address) and `CONTACT_RECIPIENT_EMAIL` are **required**; SMTP defaults to Google Workspace relay (`smtp-relay.gmail.com:587`) unless you override `EMAIL_HOST` / related vars |

Do not commit real production SMTP credentials. Prefer the comments in `.env.example` when adding new mail-related env vars.

### Checklist if something fails

1. `.env` exists in the repo root (same folder as `manage.py`).
2. `SECRET_KEY` is set and non-empty.
3. **Docker:** `POSTGRES_HOST=db`; run `docker compose up` (not only `db` if you need the app).
4. **uv:** `DATABASE_URL` uses `localhost` (or your host); Postgres is running and reachable.
5. After pulling model changes: run migrations (see your path’s guide) **before** `createsuperuser`.

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

## Optional: VS Code / Cursor + Ruff

`.vscode` is gitignored. To format Python on save with the [Ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) extension, add `.vscode/settings.json`:

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "ruff.importStrategy": "fromEnvironment"
}
```

---

## Next steps

- [Docker deployment](docker-deployment.md)
- [Local deployment (uv)](local-deployment.md)
- [Developer documentation index](README.md)
