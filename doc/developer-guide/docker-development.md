# Docker development

Run the full stack in Docker: web app, PostgreSQL, and Tailwind CSS watch.

**Before starting:** [Configure `.env`](01-getting-started.md#environment-file-env) for the Docker example (`POSTGRES_HOST=db`).

All commands are from the **repository root**.

---

## Start

Foreground (logs in terminal):

```bash
docker compose up
```

Background:

```bash
docker compose up -d
```

| URL | Purpose |
|-----|---------|
| http://localhost:8000 | Public site |
| http://localhost:8000/wagtail/ | Wagtail admin |

`compose.yaml` runs `runserver_plus` on port 8000 and starts `db` + `tailwind` with the web service.

---

## First-time setup

**Create an admin user** (Wagtail login):

```bash
docker compose exec web python manage.py createsuperuser
```

**Migrations** — apply if the database is new or after pulling model changes:

```bash
docker compose exec web python manage.py migrate
```

---

## Everyday commands

Prefix app commands with `docker compose exec web`:

| Task | Command |
|------|---------|
| Migrate | `docker compose exec web python manage.py migrate` |
| New migrations | `docker compose exec web python manage.py makemigrations cms` |
| Django shell | `docker compose exec web python manage.py shell` |
| Add dependency | `docker compose exec web uv add <package>` |
| Add dev dependency | `docker compose exec web uv add --group dev <package>` |
| Tests | `docker compose exec web python manage.py test cms.tests --settings core.settings.test` |

Commit new files under `cms/migrations/` after `makemigrations`.

---

## Reset environment

Remove containers and images:

```bash
docker compose down --rmi
```

---

## Related

- [Getting started — `.env`](01-getting-started.md)
- [Local development (uv)](local-development.md) — alternative path
- [Developer guide index](README.md)
