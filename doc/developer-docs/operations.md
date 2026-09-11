# Operations

Day-to-day repo operations for developers — CI, migrations, dependencies.

---

## CI and quality

| Workflow | Role |
|----------|------|
| [`.github/workflows/ruff.yaml`](../../.github/workflows/ruff.yaml) | Python lint and format (required on PRs) |
| [`.github/workflows/yamllint.yaml`](../../.github/workflows/yamllint.yaml) | YAML lint |
| [`.github/workflows/trivy-*.yaml`](../../.github/workflows/) | Container / dependency scanning |
| [`.github/workflows/pa11y.yaml`](../../.github/workflows/pa11y.yaml) | Accessibility checks |

Before pushing:

```bash
uv run ruff check .
uv run ruff format --check .
```

Optional locally: [pre-commit](getting-started.md#optional-pre-commit).

---

## Migrations

- App with models: **`cms`** — run `makemigrations cms` after model changes.
- Commit migration files with the PR.

**After first deploy to a shared database:** migrations are **append-only**. Add `0002_…`, `0003_…`. Do not rewrite `0001_initial.py` once applied anywhere.

If `migrate` says nothing to apply but tables are missing, the DB history is out of sync — coordinate with the team (often dev DB reset: `docker compose down -v` and migrate fresh).

Details: [dev conventions — migrations](dev-conventions.md#process-and-pull-requests).

---

## Dependencies (uv)

- Lockfile: `uv.lock` — commit when dependencies change.
- Add package: `uv add <package>` (updates `pyproject.toml` and lock).
- Sync env: `uv sync`

Python version and tools are defined in `pyproject.toml` (Ruff, pytest settings).

---

## Docker services

`compose.yaml` — typical dev stack:

| Service | Role |
|---------|------|
| `web` | Django / Wagtail |
| `db` | PostgreSQL |
| `tailwind` | Rebuilds `cms/static/cms/css/portal.css` from `base.css` |

See [Docker deployment](docker-deployment.md) and [troubleshooting — Tailwind](troubleshooting.md#tailwind-css-not-updating).

---

## Logging

Production logging uses **django-structlog** — [ADR-0008](../architecture/decisions/0008-use-django-structlog-for-logging.md). Use structlog in new CMS/service code; avoid bare `print` in application paths.

---

## Related

- [Getting started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
- [Developer conventions](dev-conventions.md)
