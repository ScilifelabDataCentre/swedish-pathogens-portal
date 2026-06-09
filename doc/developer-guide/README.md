# Developer guide

For contributors to `spp-wagtail`.

**New here?** [Getting started](01-getting-started.md) → [Docker](docker-development.md) or [uv](local-development.md) → [repository tour](02-repository-tour.md) → [how-tos](04-how-to-guides/).

---

## Contents

| Topic | Doc |
|-------|-----|
| Environment (`.env`, prerequisites) | [01-getting-started.md](01-getting-started.md) |
| Docker | [docker-development.md](docker-development.md) |
| Local uv | [local-development.md](local-development.md) |
| Repo layout | [02-repository-tour.md](02-repository-tour.md) |
| Add a page type | [add-a-page-type.md](04-how-to-guides/add-a-page-type.md) |
| Add a StreamField block | [add-a-streamfield-block.md](04-how-to-guides/add-a-streamfield-block.md) |
| Add a snippet | [add-a-snippet.md](04-how-to-guides/add-a-snippet.md) |
| PR conventions | [conventions-from-prs.md](conventions-from-prs.md) |

---

## Run tests

```bash
# Local
uv run python manage.py test cms.tests --settings core.settings.test

# Docker
docker compose exec web python manage.py test cms.tests --settings core.settings.test
```

---

## PR expectations

From [`.github/pull_request_template.md`](../../.github/pull_request_template.md) and [Ruff CI](../../.github/workflows/ruff.yaml):

- PR title: `FREYA-XXXX: Short description`
- Link Jira in the PR description
- Ruff lint/format must pass
- Model changes: `makemigrations cms` and commit migrations
- Run tests for the area you changed

More detail: [conventions-from-prs.md](conventions-from-prs.md).

---

## Related

- [Documentation index](../README.md)
- [ADRs](../architecture/decisions/)
