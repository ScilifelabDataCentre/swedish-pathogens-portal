# Docker deployment

Run the full stack in Docker: web app, PostgreSQL, and Tailwind CSS watch.

**Before starting:** [Configure `.env`](getting-started.md#environment-file-env) for the Docker example (`POSTGRES_HOST=db`).

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

### Optional: Mailpit (local email)

To catch outbound mail in a web UI:

```bash
docker compose --profile mailpit up
```

| URL | Purpose |
|-----|---------|
| http://localhost:8025 | Mailpit UI |
| `localhost:1025` | SMTP (Compose sets `EMAIL_HOST=mailpit` on `web`) |

Without the profile, contact-form sends fail gracefully (`EMAIL_SEND_ERROR`) and do not crash the app. More: [Getting started — email](getting-started.md#email-local-and-production).

---

## First-time setup

Apply migrations **before** creating a superuser (a fresh DB has no auth tables until migrate runs):

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

After pulling model changes, run `migrate` again. If you add or change models yourself, create migrations then apply them:

```bash
docker compose exec web python manage.py makemigrations cms
docker compose exec web python manage.py migrate
```

Commit new files under `cms/migrations/` with your PR.

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

---

## Reset environment

Remove containers and images:

```bash
docker compose down --rmi all
```

To also wipe the Postgres volume (full DB reset):

```bash
docker compose down -v --rmi all
```

---

## Related

- [Getting started — `.env`](getting-started.md)
- [Local deployment (uv)](local-deployment.md) — alternative path
- [Developer documentation index](README.md)
