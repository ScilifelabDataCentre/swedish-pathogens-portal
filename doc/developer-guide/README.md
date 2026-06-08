# Developer guide

For contributors to `spp-wagtail`. Editors: see the [editor guide](../editor-guide/README.md).

**New here?** [Getting started](01-getting-started.md) (`.env`) → [Docker](docker-development.md) or [uv](local-development.md) → conventions → how-tos when you build something.

---

## Docs to write (in order)

| # | Topic | Files |
|---|--------|-------|
| 1 | **Getting started** | [01-getting-started.md](01-getting-started.md), [docker-development.md](docker-development.md), [local-development.md](local-development.md) |
| 2 | **Repository tour** | `02-repository-tour/` — `core/` vs `cms/`, page tree, Tailwind/htmx |
| 3 | **Conventions** | `03-conventions/` — style ([ADR-0003](../architecture/decisions/0003-formatting-rules.md)), Wagtail patterns, PR expectations |
| 4 | **How-tos** | `04-how-to-guides/` — see list below |
| 5 | **Testing** | `05-testing/` — when and how to run tests |

**Layout (today):** `core/` = Django project config; `cms/` = pages (`cms/pages/`), blocks, snippets, services, templates.

---

## How-to guides (core only)

Add these as needed — not one doc per minor feature.

| Guide | Covers |
|-------|--------|
| [add-a-page-type.md](04-how-to-guides/add-a-page-type.md) | New page model, template, migration, admin |
| [add-a-streamfield-block.md](04-how-to-guides/add-a-streamfield-block.md) | Block + template |
| [add-a-snippet.md](04-how-to-guides/add-a-snippet.md) | Snippet model and admin |

Special topics (dashboards, portal data, HTMX listings) get a guide **when someone needs them**, not upfront in the index.

**Examples in code:** `cms/pages/standard_page.py`, `news_index.py` / `news.py`, `catalogue.py`.

---

## Run tests

**Local (uv):**

```bash
uv run python manage.py test cms.tests --settings core.settings.test
```

**Docker:**

```bash
docker compose exec web python manage.py test cms.tests --settings core.settings.test
```

---

## PR expectations (from repo checklist)

These come from [`.github/pull_request_template.md`](../../.github/pull_request_template.md) and CI — not a separate doc for now.

- PR title: `FREYA-XXXX: Short description`
- Link Jira in the PR description
- Ruff lint/format must pass (see [`.github/workflows/ruff.yaml`](../../.github/workflows/ruff.yaml))
- Model changes: `makemigrations cms` and commit migrations when applicable
- Run tests for the area you changed

---

## Related

- [Documentation index](../README.md)
- [Editor guide](../editor-guide/README.md)
- [ADRs](../architecture/decisions/)
