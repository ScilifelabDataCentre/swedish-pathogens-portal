# Developer conventions

Index of **how we work and write code** in `spp-wagtail`. Each rule links to its source — [team decision](decisions/README.md), merged PR, [architecture ADR](../architecture/decisions/), or guide.

When a convention changes, update this file and add or update a [decision](decisions/template.md) if the team agreed it in a meeting.

---

## Convention index

| Convention | Source |
|------------|--------|
| Workflow-impacting changes need team discussion + decision doc | [Decision: workflow change](decisions/workflow-change-discussion.md) |
| PR title `FREYA-XXXX: …`, link Jira, pass Ruff CI | [PR template](../../.github/pull_request_template.md), [Ruff workflow](../../.github/workflows/ruff.yaml) |
| Model changes → `makemigrations cms`, commit migration, run tests | [Developer guide — PR expectations](README.md#pr-expectations) |
| Migrations append-only after first deploy | [PR #46](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/46) review; navigation PR (FREYA-2213) |
| One page type per file under `cms/pages/` | [Repository tour](repository-tour.md), [How-to: page type](how-to-guides/add-a-page-type.md) |
| Prefer sub-pages over snippets when content has its own URL | [How-to: page type](how-to-guides/add-a-page-type.md), [How-to: snippet](how-to-guides/add-a-snippet.md), [ADR-0006](../architecture/decisions/0006-adopt-wagtail-as-cms.md) |
| Blocks in `cms/blocks/`, snippets in `cms/snippets/`, shared CMS logic in `cms/services/` | [Repository tour](repository-tour.md) |
| File names: lowercase with underscores | [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| Google-style docstrings on non-trivial code; Ruff for Python | [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| Inline type hints at empty `{}` / `[]` init | [Decision: inline typing](decisions/inline-type-hinting-at-init.md), [PR #49](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/49) |
| `RichTextBlock`: explicit `features=[...]` allowlist | PR review `senthil/base-blocks` (FREYA-2217–2220) |
| `help_text` on fields, blocks, and panels | PR review `senthil/base-blocks`; [How-to: block](how-to-guides/add-a-streamfield-block.md) |
| Child-page card blocks: safe fallbacks for generic `Page` | PR review `senthil/base-blocks` (FREYA-2220) |
| Navigation menus as snippets; slug `header` / `footer` matches templates | PR review FREYA-2213/2214 (`senthil/header-navigation-menu`) |
| Shared `validate_filters` + `@htmx_request_with_url_update()` | [PR #46](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/46) |
| Tailwind `@source` scans `cms/` and `core/` | [PR #48](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/48), [Repository tour — frontend](repository-tour.md) |
| Run `cms.tests` with `core.settings.test` | [Developer guide — tests](README.md#run-tests) |
| `.env` setup (Docker vs uv) | [Getting started](getting-started.md), [Docker](docker-development.md), [Local uv](local-development.md) |
| Responsive test breakpoint (`md` vs `lg`) | [Decision: breakpoint](decisions/responsive-breakpoint-for-testing.md) — *ongoing* |
| Dashboard slug matches page, snippet, and `VIZ_MODULES` | [How-to: dashboard](how-to-guides/add-a-dashboard.md) |
| Dashboard `figure_id` keys match `generate_figures` output | [How-to: dashboard](how-to-guides/add-a-dashboard.md) |

---

## Process and pull requests

| Rule | Detail |
|------|--------|
| **PR title** | `FREYA-XXXX: Short description` — [PR template](../../.github/pull_request_template.md) |
| **Description** | Link Jira; note migrations, manual test steps, admin checks |
| **CI** | Ruff lint and format must pass |
| **Workflow changes** | Discuss in sprint; add or link a [decision doc](decisions/workflow-change-discussion.md) and reference it in the PR |
| **Model changes** | `makemigrations cms`, commit migration, run tests for the area you changed |

**Migrations after first shared deploy:** append-only (`0002_…`, `0003_…`). Do not rewrite `0001_initial.py` once applied — DBs report “No migrations to apply” while tables are missing.

---

## Layout and naming

| Rule | Detail |
|------|--------|
| **Page types** | One Python file per type in `cms/pages/` — [how-to](how-to-guides/add-a-page-type.md) |
| **Pages vs snippets** | Own URL → page under an index; small reusable record → snippet — [page how-to](how-to-guides/add-a-page-type.md), [snippet how-to](how-to-guides/add-a-snippet.md) |
| **File names** | `lowercase_with_underscores` — [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| **URLs** | Lowercase with hyphens (Django slugs) — [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |

---

## Wagtail content models

- **`RichTextBlock`:** pass an explicit `features=[...]` allowlist. Omitting `features` uses Draftail defaults (often wider than intended).

```python
blocks.RichTextBlock(
    features=["h2", "h3", "bold", "italic", "link", "ol", "ul"],
)
```

- **`help_text`:** on fields, block `Meta`, and panels so admin matches templates.
- **Child-page listings:** do not assume every `Page` has `thumbnail` or `description`; use `search_description`, page-type fields, or `get_context` fallbacks.
- **Navigation snippets:** `NavigationMenu.slug` must be `header` or `footer` to match `{% get_menu "header" %}` in templates; document in snippet `help_text`.

---

## Shared services (filters and HTMX)

From [PR #46](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/46) — `cms/services/validators.py`, `cms/services/decorators.py`.

- **`validate_filters`:** pass `expected_keys` per page (catalogue: `{"search", "type"}`; highlights: all three). Invalid params → `Http404`.
- **HTMX `serve`:** set `htmx_template` on the page class; decorate `serve` with `@htmx_request_with_url_update()`.

```python
htmx_template = "cms/components/catalogue_list.html#catalogue_grid"

@htmx_request_with_url_update()
def serve(self, request, *args, **kwargs):
    return super().serve(request, *args, **kwargs)
```

- **Tests:** unit-test extracted `validators` / `decorators`; add a template render test when a block can 500 on generic pages.

---

## Typing

[Decision: inline type hinting at init](decisions/inline-type-hinting-at-init.md) · [PR #49](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/49) · [ADR-0003](../architecture/decisions/0003-formatting-rules.md)

```python
cards: list[dict[str, Any]] = []
all_dashboards: dict[str, PageQuerySet] = {}
```

Match key types to stored values (`int` FK ids vs `str`). Prefer precise return types on shared helpers over `Any`.

---

## Frontend (Tailwind)

[Repository tour](repository-tour.md) · [PR #48](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/48)

| Rule | Detail |
|------|--------|
| **`@source`** | `cms/static/cms/css/base.css` must scan `cms/` and `core/`; add a line for new template apps |
| **DaisyUI** | Keep `@source not` guards for `daisyui*.mjs` (see comments in `base.css`) |

---

## Tests

```bash
uv run python manage.py test cms.tests --settings core.settings.test
```

Run the module you touched. Model-only tests do not cover admin `Form.clean()` — extract validators or add form tests when validation is critical.

---

## Team decisions

Full records (context, logic, status): [decisions/](decisions/README.md)

| Decision | Status |
|----------|--------|
| [Inline type hinting at empty init](decisions/inline-type-hinting-at-init.md) | decision |
| [Workflow changes need team discussion](decisions/workflow-change-discussion.md) | decision |
| [Responsive breakpoint for layout testing](decisions/responsive-breakpoint-for-testing.md) | ongoing discussion |

New decisions: copy [decisions/template.md](decisions/template.md), add a row to the table above and to [decisions/README.md](decisions/README.md), then link from the relevant section here.

---

## Architecture ADRs

Stack and system design — link, do not duplicate:

| ADR | Topic |
|-----|--------|
| [0003](../architecture/decisions/0003-formatting-rules.md) | Formatting, Ruff, file names, docstrings |
| [0006](../architecture/decisions/0006-adopt-wagtail-as-cms.md) | Wagtail as CMS |
| [0005](../architecture/decisions/0005-adopt-daisy-ui-for-ui-components.md) | DaisyUI |
| [0008](../architecture/decisions/0008-use-django-structlog-for-logging.md) | Logging |

Full list: [doc index](../README.md#architecture-decision-records).

---

## Dashboards

[How-to: add a dashboard](how-to-guides/add-a-dashboard.md) · [ADR-0004](../architecture/decisions/0004-visualisation-tool-for-dashboards.md)

- **Slug alignment:** `DashboardPage.slug` = `DashboardData.dashboard_slug` = `VIZ_MODULES` key.
- **Figures:** viz module returns `dict[figure_id, json]`; `PlotlyFigureBlock.figure_id` must match.
- **Upload:** CSV only; figures regenerate on source file change via `dashboard_visualisation.generate_figures`.

---

## Related guides

- [Getting started](getting-started.md) — `.env`, prerequisites
- [Repository tour](repository-tour.md) — folder layout
- [How-to guides](how-to-guides/) — page, block, snippet, dashboard
