# Local deployment (uv)

Run Django on your machine with **uv**, connecting to PostgreSQL on `localhost`.

**Before starting:** [Configure `.env`](getting-started.md#environment-file-env) for the uv example (`POSTGRES_HOST=localhost` and `DATABASE_URL=psql://app:password@localhost:5432/spp`).

All commands are from the **repository root**. Settings module defaults to `core.settings.development` (`manage.py`).

---

## PostgreSQL

The app needs a running Postgres that matches your `.env` credentials.

**Option A — DB container with published port**

Default `compose.yaml` does not expose Postgres to the host. Publish port 5432, e.g. create `compose.override.yaml`:

```yaml
services:
  db:
    ports:
      - "5432:5432"
```

Then:

```bash
docker compose up -d db
```

**Option B — Postgres installed on the host**

Use the same `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` as in `.env`, or adjust `.env` and `DATABASE_URL` to match your install.

---

## Install and run

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000 | Public site |
| http://127.0.0.1:8000/wagtail/ | Wagtail admin |

Run `migrate` before `createsuperuser` on a fresh database.

---

## Frontend (Tailwind)

The Docker **tailwind** service watches and rebuilds `portal.css`. On a pure uv setup that service is not running — either:

- run the full Docker stack when changing CSS, or  
- run Tailwind yourself (see `cms/static/cms/css/base.css` and the `tailwind` service command in `compose.yaml`).

---

## Everyday commands

| Task | Command |
|------|---------|
| Migrate | `uv run python manage.py migrate` |
| New migrations | `uv run python manage.py makemigrations cms` |
| Django shell | `uv run python manage.py shell` |
| Add dependency | `uv add <package>` |
| Add dev dependency | `uv add --group dev <package>` |
| Tests | Prefer Docker — see [testing.md](testing.md) (`core.settings.test` needs PostgreSQL) |

Commit new files under `cms/migrations/` after `makemigrations`.

---

## Related

- [Getting started — `.env`](getting-started.md)
- [Docker deployment](docker-deployment.md) — recommended if you want Tailwind watch without extra setup
- [Developer documentation index](README.md)
