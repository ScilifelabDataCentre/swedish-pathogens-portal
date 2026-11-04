# Operations

Day-to-day repo operations for developers — CI, migrations, dependencies.

---

## CI and quality

| Workflow | Role |
|----------|------|
| [`.github/workflows/ruff.yaml`](../../.github/workflows/ruff.yaml) | Python lint and format (required on PRs) |
| [`.github/workflows/django-tests.yaml`](../../.github/workflows/django-tests.yaml) | Django / Wagtail test suite |
| [`.github/workflows/yamllint.yaml`](../../.github/workflows/yamllint.yaml) | YAML lint |
| [`.github/workflows/pa11y.yaml`](../../.github/workflows/pa11y.yaml) | Accessibility checks |
| [`.github/workflows/linkchecker.yaml`](../../.github/workflows/linkchecker.yaml) | Link checks (known false positives whitelisted — [decision](decisions/linkchecker-whitelist.md)) |
| [`.github/workflows/trivy-*.yaml`](../../.github/workflows/) | Container / dependency scanning ([decision](decisions/renovate-and-trivy.md)) |
| [`.github/workflows/publish-image.yaml`](../../.github/workflows/publish-image.yaml) | Container image publish |

Before pushing:

```bash
uv run ruff check .
uv run ruff format --check .
```

Optional locally: [pre-commit](getting-started.md#optional-pre-commit).

### Renovate

Security dependency updates land promptly. Other updates are batched into a **bulk PR once per sprint** (target: first Tuesday) so the team can review without constant noise — [decision](decisions/renovate-and-trivy.md).

### Trivy

Scheduled scans remain. Branch scans are scoped so failures relate to the change set — [decision](decisions/renovate-and-trivy.md).

### Link checker

Whitelist persistent false positives (e.g. bot-blocked `doi.org` links) in the workflow config rather than “fixing” the remote site — [decision](decisions/linkchecker-whitelist.md).

---

## Migrations

- App with models: **`cms`** — run `makemigrations cms` after model changes.
- Commit migration files with the PR (`cms/migrations/` is **tracked**).

**History:** During pre-launch development, migrations were temporarily gitignored, then replaced with a baseline at Wagtail cutover — [decision](decisions/migration-files-policy.md).

**After first deploy to a shared database:** migrations are **append-only**. Add `0002_…`, `0003_…`. Do not rewrite `0001_initial.py` once applied anywhere.

If `migrate` says nothing to apply but tables are missing, the DB history is out of sync — coordinate with the team (often dev DB reset: `docker compose down -v` and migrate fresh).

Details: [dev conventions — migrations](dev-conventions.md#process-and-pull-requests).

---

## Dependencies (uv)

uv is the standard Python environment tool — [decision](decisions/uv-as-standard-environment.md).

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
| `mailpit` | Optional SMTP catcher (`--profile mailpit`) — UI http://localhost:8025 |

See [Docker deployment](docker-deployment.md), [Getting started — email](getting-started.md#email-local-and-production), and [troubleshooting — Tailwind](troubleshooting.md#tailwind-css-not-updating).

---

## Logging

Production logging uses **django-structlog** — [ADR-0008](../architecture/decisions/0008-use-django-structlog-for-logging.md). Use structlog in new CMS/service code; avoid bare `print` in application paths. Broader observability dashboards may follow Data Centre / Agar work; until then keep structlog as-is.

---

## Related

- [Getting started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
- [Developer conventions](dev-conventions.md)
- [Team decisions](decisions/README.md)
