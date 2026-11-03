# Conventions

Index of **how we work and write code** in the Swedish Pathogens Portal. Each rule links to its source — [team decision](decisions/README.md), merged PR, [architecture ADR](../architecture/decisions/), or guide.

When a convention changes, update this file and add or update a [team decision](decisions/template.md) if agreed in a meeting. Full Freya archive: [Decision archive](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/3676930125/Decision+archive).

---

## Convention index

| Convention | Source |
|------------|--------|
| Workflow-impacting changes need team discussion + decision doc | [Decision: workflow change](decisions/workflow-change-discussion.md) |
| PR title `FREYA-XXXX: …`, link Jira, pass Ruff CI | [PR template](../../.github/pull_request_template.md), [Ruff workflow](../../.github/workflows/ruff.yaml) |
| Model changes → `makemigrations cms`, commit migration, run tests | [Developer docs — PR expectations](README.md#pr-expectations) |
| Migrations tracked; append-only after shared deploy | [Decision: migration files](decisions/migration-files-policy.md), [Operations](operations.md#migrations) |
| One page type per file under `cms/pages/` | [PR #38](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/38), [How-to: page type](how-to-guides/add-a-page-type.md) |
| Prefer sub-pages over snippets when content has its own URL | [How-to: page type](how-to-guides/add-a-page-type.md), [How-to: snippet](how-to-guides/add-a-snippet.md), [ADR-0006](../architecture/decisions/0006-adopt-wagtail-as-cms.md) |
| Blocks in `cms/blocks/`, snippets in `cms/snippets/`, shared CMS logic in `cms/services/` | [Repository tour](repository-tour.md) |
| File names: lowercase with underscores | [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| Do not commit personal/local-only tooling | [Decision: repository files](decisions/repository-files-policy.md) |
| Google-style docstrings on non-trivial code; Ruff for Python | [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| Inline type hints at empty `{}` / `[]` init | [Decision: inline typing](decisions/inline-type-hinting-at-init.md), [PR #49](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/49) |
| Standard Python env: **uv** | [Decision: uv](decisions/uv-as-standard-environment.md) |
| `RichTextBlock`: explicit `features=[...]` allowlist | PR review `senthil/base-blocks` (FREYA-2217–2220) |
| `help_text` on fields, blocks, and panels | PR review `senthil/base-blocks`; [How-to: block](how-to-guides/add-a-streamfield-block.md) |
| Card descriptions: italics OK, no hyperlinks; keep truncation, shorten copy | [Decision: cards](decisions/card-truncation-and-rich-text.md) |
| Child-page card blocks: safe fallbacks for generic `Page` | PR review `senthil/base-blocks` (FREYA-2220) |
| Page copy disabled in admin (when publish controls on) | [Decision: disable page copy](decisions/disable-page-copy.md), [PR #111](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/111) |
| Images: jpeg/png/webp upload; renditions as webp | [Decision: image formats](decisions/image-format-policy.md) |
| Standardised alert block style (not reused for other UI) | [Decision: alerts](decisions/alert-template-standardisation.md) |
| Sticky header (hide on scroll down) | [Decision: sticky header](decisions/sticky-header.md) |
| Navigation menus as snippets; slug `header` / `footer` matches templates | PR review FREYA-2213/2214 (`senthil/header-navigation-menu`) |
| Shared `validate_filters` + `@htmx_request_with_url_update()` | [PR #46](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/46) |
| Tailwind `@source` scans `cms/` and `core/` | [PR #48](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/48), [Repository tour — frontend](repository-tour.md) |
| Run `cms.tests` with `core.settings.test` | [Developer docs — tests](README.md#run-tests) |
| `.env` setup (Docker vs uv) | [Getting started](getting-started.md), [Docker deployment](docker-deployment.md), [Local deployment](local-deployment.md) |
| Responsive test breakpoint (`md` vs `lg`) | [Decision: breakpoint](decisions/responsive-breakpoint-for-testing.md) — *ongoing* |
| Dashboard slug matches page, snippet, and `VIZ_MODULES` | [How-to: dashboard](how-to-guides/add-a-dashboard.md) |
| Dashboard `figure_id` keys match `generate_figures` output | [How-to: dashboard](how-to-guides/add-a-dashboard.md) |
| External rich-text links: new tab + `rel="noopener noreferrer"` | [PR #31](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/31) — `cms/handlers/external_link.py`, `wagtail_hooks.py` |
| Portal data views in `portal_data/views.py` (not page model) | [PR #50](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/50) |
| Prefer Wagtail admin; minimise superusers; MFA before expanding access | [Decision: admin access](decisions/admin-access-policy.md) |
| Renovate bulk non-security updates; scoped Trivy branch scans | [Decision: Renovate/Trivy](decisions/renovate-and-trivy.md), [Operations](operations.md) |
| Linkchecker whitelist for false positives | [Decision: linkchecker](decisions/linkchecker-whitelist.md) |
| Tests: `core.settings.test`; build page trees in each test module | [Testing](testing.md) |

---

## Process and pull requests

| Rule | Detail |
|------|--------|
| **PR title** | `FREYA-XXXX: Short description` — [PR template](../../.github/pull_request_template.md) |
| **Description** | Link Jira; note migrations, manual test steps, admin checks |
| **CI** | Ruff lint and format must pass; run tests for the area you changed |
| **Workflow changes** | Discuss in sprint; add or link a [decision doc](decisions/workflow-change-discussion.md) and reference it in the PR |
| **Model changes** | `makemigrations cms`, commit migration, run tests for the area you changed |
| **Repo files** | Personal/local-only tooling → `.gitignore` — [repository files](decisions/repository-files-policy.md) |

**Migrations after first shared deploy:** append-only (`0002_…`, `0003_…`). Do not rewrite applied migrations — [migration files policy](decisions/migration-files-policy.md).

---

## Layout and naming

| Rule | Detail |
|------|--------|
| **Page types** | One Python file per type in `cms/pages/` — [how-to](how-to-guides/add-a-page-type.md) |
| **Pages vs snippets** | Own URL → page under an index; small reusable record → snippet — [page how-to](how-to-guides/add-a-page-type.md), [snippet how-to](how-to-guides/add-a-snippet.md) |
| **File names** | `lowercase_with_underscores` — [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| **URLs** | Lowercase with hyphens (Django slugs) — [ADR-0003](../architecture/decisions/0003-formatting-rules.md) |
| **Tooling** | **uv** for Python envs — [decision](decisions/uv-as-standard-environment.md) |

---

## Wagtail content models

- **`RichTextBlock`:** pass an explicit `features=[...]` allowlist. Omitting `features` uses Draftail defaults (often wider than intended).

```python
blocks.RichTextBlock(
    features=["h2", "h3", "bold", "italic", "link", "ol", "ul"],
)
```

- **`help_text`:** on fields, block `Meta`, and panels so admin matches templates.
- **Cards:** keep UI truncation; write short titles/descriptions. Descriptions may use italics; **no hyperlinks** in card descriptions — [decision](decisions/card-truncation-and-rich-text.md).
- **Child-page listings:** do not assume every `Page` has `thumbnail` or `description`; use `search_description`, page-type fields, or `get_context` fallbacks.
- **Page copy:** disabled when publish controls are on (`DISABLE_DIRECT_PUBLISH`) — create a new page instead — [decision](decisions/disable-page-copy.md), `cms/wagtail_hooks.py`.
- **Images:** allow `jpeg`/`jpg`/`png`/`webp`; renditions convert to WebP — [decision](decisions/image-format-policy.md), `core/settings/base.py`.
- **Alerts:** use the shared alert block/style; do not reuse that look for unrelated UI — [decision](decisions/alert-template-standardisation.md).
- **Navigation snippets:** `NavigationMenu.slug` must be `header` or `footer` to match `{% get_menu "header" %}` in templates; document in snippet `help_text`.
- **External links:** register `ExternalLinkNewTabHandler` via `register_rich_text_features` in `cms/wagtail_hooks.py` — opens in new tab with `noopener` / `noreferrer` ([PR #31](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/31)).
- **Admin access:** Wagtail-first; minimise superusers — [decision](decisions/admin-access-policy.md).

---

## Shared services (filters and HTMX)

From [PR #46](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/46) — `cms/services/validators.py`, `cms/services/decorators.py`.

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

[Decision: inline type hinting at init](decisions/inline-type-hinting-at-init.md) · [PR #49](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/49) · [ADR-0003](../architecture/decisions/0003-formatting-rules.md)

```python
cards: list[dict[str, Any]] = []
all_dashboards: dict[str, PageQuerySet] = {}
```

Match key types to stored values (`int` FK ids vs `str`). Prefer precise return types on shared helpers over `Any`.

---

## Frontend (Tailwind)

[Repository tour](repository-tour.md) · [PR #48](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/48)

| Rule | Detail |
|------|--------|
| **`@source`** | `cms/static/cms/css/base.css` must scan `cms/` and `core/`; add a line for new template apps |
| **DaisyUI** | Keep `@source not` guards for `daisyui*.mjs` (see comments in `base.css`) |
| **Header** | Sticky; hide on scroll down — [decision](decisions/sticky-header.md) |

---

## Tests

[Testing](testing.md)

```bash
docker compose exec web python manage.py test cms.tests --settings core.settings.test
```

Tests need PostgreSQL — prefer Docker ([testing.md](testing.md)). Run the module you touched. Model-only tests do not cover admin `Form.clean()` — extract validators or add form tests when validation is critical.

---

## Team decisions

Full records (context, logic, status): [decisions/](decisions/README.md)

| Decision | Status |
|----------|--------|
| [Inline type hinting at empty init](decisions/inline-type-hinting-at-init.md) | decision |
| [Workflow changes need team discussion](decisions/workflow-change-discussion.md) | decision |
| [Card truncation and rich text](decisions/card-truncation-and-rich-text.md) | decision |
| [Disable page copy](decisions/disable-page-copy.md) | decision |
| [Image format policy](decisions/image-format-policy.md) | decision |
| [Migration files policy](decisions/migration-files-policy.md) | decision |
| [Repository files policy](decisions/repository-files-policy.md) | decision |
| [uv as standard environment](decisions/uv-as-standard-environment.md) | decision |
| [Alert template standardisation](decisions/alert-template-standardisation.md) | decision |
| [Sticky header](decisions/sticky-header.md) | decision |
| [Admin access policy](decisions/admin-access-policy.md) | decision |
| [Renovate and Trivy](decisions/renovate-and-trivy.md) | decision |
| [Linkchecker whitelist](decisions/linkchecker-whitelist.md) | decision |
| [Responsive breakpoint for layout testing](decisions/responsive-breakpoint-for-testing.md) | ongoing discussion |

New decisions: copy [decisions/template.md](decisions/template.md), add a row to the table above and to [decisions/README.md](decisions/README.md), then link from the relevant section here.

---

## Team Freya process (Confluence)

Sprint culture, remote/flex rules, deployment rota, release windows, and other **team process** decisions live in Confluence, not duplicated in this repo:

- [Decision archive](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/3676930125/Decision+archive)
- [Team Freya sprints & culture](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/2773680241/Team+Freya+sprints+culture)
- [Regular release schedule](https://scilifelab.atlassian.net/wiki/spaces/TE/pages/3676242048/Regular+release+schedule)

When a process decision changes how we write or ship **this** codebase, add a short in-repo [decision](decisions/template.md) and a row in the tables above.

---

## Architecture ADRs

Stack and system design — link, do not duplicate:

| ADR | Topic |
|-----|--------|
| [0003](../architecture/decisions/0003-formatting-rules.md) | Formatting, Ruff, file names, docstrings |
| [0006](../architecture/decisions/0006-adopt-wagtail-as-cms.md) | Wagtail as CMS |
| [0005](../architecture/decisions/0005-adopt-daisy-ui-for-ui-components.md) | DaisyUI |
| [0008](../architecture/decisions/0008-use-django-structlog-for-logging.md) | Logging |
| [0011](../architecture/decisions/0011-django-allauth-for-authentication.md) | Admin authentication |

Full list: [doc index](../README.md#architecture-decision-records).

---

## Dashboards

[How-to: add a dashboard](how-to-guides/add-a-dashboard.md) · [Dashboard uploads](dashboard_uploads.md) · [ADR-0004](../architecture/decisions/0004-visualisation-tool-for-dashboards.md) · [ADR-0014](../architecture/decisions/0014-dashboard-data-flow-strategy.md)

- **Slug alignment:** `DashboardPage.slug` = `DashboardData.dashboard_slug` = `VIZ_MODULES` key.
- **Figures:** viz module returns `dict[figure_id, json]`; `PlotlyFigureBlock.figure_id` must match.
- **Upload:** CSV only; figures regenerate on source file change via `dashboard_visualisation.generate_figures`.

---

## Portal data

[Portal Data guide](portal_data.md) · [PR #50](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/pull/50) — routable `PortalDataPage` delegates file listing and downloads to `portal_data/views.py`; context building stays in `portal_data/context.py`. Datatypes configured in `portal_data/services.py` (`SUPPORTED_TYPES`).

---

## Related guides

- [Getting started](getting-started.md) — `.env`, prerequisites
- [Repository tour](repository-tour.md) — folder layout
- [How-to guides](how-to-guides/) — page, block, snippet, dashboard
- [Testing](testing.md) · [Operations](operations.md) · [Troubleshooting](troubleshooting.md)
