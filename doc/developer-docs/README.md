# Developer documentation

Setup, conventions, and how-tos for **developing** `spp-wagtail`. Wagtail admin help: [Wagtail docs](https://docs.wagtail.org/).

**New here?** [Getting started](getting-started.md) → [Docker](docker-deployment.md) or [uv](local-deployment.md) → [repository tour](repository-tour.md) → [how-tos](how-to-guides/).

---

## Contents

| Topic | Doc |
|-------|-----|
| Environment (`.env`, prerequisites) | [getting-started.md](getting-started.md) |
| Docker deployment | [docker-deployment.md](docker-deployment.md) |
| Local deployment (uv) | [local-deployment.md](local-deployment.md) |
| Repo layout | [repository-tour.md](repository-tour.md) |
| Add a page type | [add-a-page-type.md](how-to-guides/add-a-page-type.md) |
| Add a StreamField block | [add-a-streamfield-block.md](how-to-guides/add-a-streamfield-block.md) |
| Add a snippet | [add-a-snippet.md](how-to-guides/add-a-snippet.md) |
| Add a dashboard | [add-a-dashboard.md](how-to-guides/add-a-dashboard.md) |
| Conventions | [dev-conventions.md](dev-conventions.md) |
| Team decisions | [decisions/](decisions/README.md) |
| Testing | [testing.md](testing.md) |
| Operations (CI, migrations, deps) | [operations.md](operations.md) |
| Troubleshooting | [troubleshooting.md](troubleshooting.md) |

---

## Run tests

```bash
# Local
uv run python manage.py test cms.tests --settings core.settings.test

# Docker
docker compose exec web python manage.py test cms.tests --settings core.settings.test
```

More: [testing.md](testing.md).

---

## PR expectations

From [`.github/pull_request_template.md`](../../.github/pull_request_template.md) and [Ruff CI](../../.github/workflows/ruff.yaml):

- PR title: `FREYA-XXXX: Short description`
- Link Jira in the PR description
- Ruff lint/format must pass
- Model changes: `makemigrations cms` and commit migrations
- Run tests for the area you changed
- Workflow-impacting changes: add or link a [decision doc](decisions/README.md)

Full index: [dev-conventions.md](dev-conventions.md).

---

## Related

- [Documentation index](../README.md)
- [Architecture ADRs](../architecture/decisions/)
