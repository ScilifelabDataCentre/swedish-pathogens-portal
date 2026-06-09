# Repository tour

Where code lives in `spp-wagtail` and how the main pieces connect.

---

## Top level

```text
spp-wagtail/
├── core/                      # Django project (settings, URLs, WSGI)
├── cms/                       # Wagtail app — pages, blocks, snippets, templates
├── dashboard_visualisation/   # Dashboard data → Plotly figure pipeline
├── portal_data/               # Portal study listing and file export logic
├── doc/                       # Guides and ADRs
├── manage.py
├── compose.yaml
├── pyproject.toml
└── uv.lock
```

- **`core/`** — project configuration only.
- **`cms/`** — Wagtail CMS and public site templates/static.
- **`dashboard_visualisation/`** and **`portal_data/`** — backend logic **outside** the Wagtail app; called from `cms/` (snippets, pages). Not separate Django apps in `INSTALLED_APPS`.

---

## `core/` — project configuration

| Path | Role |
|------|------|
| `core/settings/` | `base.py`, `development.py`, `production.py`, `test.py` |
| `core/urls.py` | Root routing: Django admin, health check, Wagtail admin, `cms/` includes, then Wagtail page URLs |
| `core/views.py` | Non-Wagtail views (e.g. `healthz`) |
| `core/templates/` | Overrides for Wagtail/Django built-ins only |

Do not add page models or CMS templates here.

---

## `cms/` — Wagtail application

| Path | Role |
|------|------|
| `cms/pages/` | Page models — **one Python file per page type**; exported in `cms/pages/__init__.py` |
| `cms/blocks/` | StreamField blocks (cards, tables, alerts, …) |
| `cms/snippets/` | Snippets (navigation, announcements, dashboard data, PLP categories) |
| `cms/services/` | Small CMS helpers (validators, HTMX decorator, data-table logic) — not dashboard/portal pipelines |
| `cms/snippets/dashboard_data.py` | Upload snippet; calls `dashboard_visualisation.generate_figures` |
| `cms/pages/dashboard*.py` | Dashboard index/detail pages; read figure JSON from snippet |
| `cms/pages/portal_data.py` | Wagtail page wrapper; calls `portal_data` package for listings/downloads |
| `cms/views/` | Non-page views (e.g. data table HTMX) |
| `cms/templates/cms/` | Page, block, and component templates |
| `cms/static/cms/` | CSS, JS, images; Tailwind input `css/base.css` → output `css/portal.css` |
| `cms/tests/` | Test modules |
| `cms/models.py` | Imports page classes from `cms.pages` so Wagtail registers them |

**Extend the site** by adding under `cms/` — new page types rarely need `core/urls.py` changes.

---

## Backend services (outside `cms/`)

| Package | Role | Wired from |
|---------|------|------------|
| `dashboard_visualisation/` | Registry and per-dashboard scripts: CSV → Plotly JSON (`registry.py`, `utils/`) | `cms/snippets/dashboard_data.py` on upload/save |
| `portal_data/` | Study metadata, facets, file listing/export (`services.py`, `context.py`) | `cms/pages/portal_data.py` (`PortalDataPage`) |

Add new dashboard viz modules under `dashboard_visualisation/` and register slugs in `registry.VIZ_MODULES`. See [how-to: add a dashboard](how-to-guides/add-a-dashboard.md). Portal data types are configured in `portal_data/services.py` (`SUPPORTED_TYPES`).

See [ADR-0004](../architecture/decisions/0004-visualisation-tool-for-dashboards.md) (Plotly) and [ADR-0007](../architecture/decisions/0007-data-hosting-architecture.md) (data hosting).

---

## Page tree and URLs

Public URLs come from the **Wagtail page tree**, not per-page URLconf entries.

```text
Wagtail root
└── HomePage (one site, max_count=1)
    ├── SectionIndexPage / index pages (news, topics, dashboards, …)
    │   └── Detail pages (NewsPage, TopicPage, …)
    └── Other top-level pages (catalogue, standard pages, …)
```

- Each page class sets `parent_page_types` and `subpage_types` — this controls what editors can add in admin.
- Slug on the page sets the URL segment; full path is built from ancestors.
- `core/urls.py` ends with `path("", include(wagtail_urls))` so unmatched paths are resolved against the tree.

Page types in code: `cms/pages/__init__.py`.

---

## Frontend

| Piece | Location / notes |
|-------|------------------|
| **Tailwind CSS v4** | Input: `cms/static/cms/css/base.css`; built CSS: `portal.css` |
| **Tailwind `@source`** | Scans `cms/` and `core/` for class names (`base.css`) |
| **DaisyUI** | Theme plugin in `base.css`; see [ADR-0005](../architecture/decisions/0005-adopt-daisy-ui-for-ui-components.md) |
| **htmx** | `django_htmx`; used for partial updates (e.g. catalogue filters) |
| **Watch in Docker** | `tailwind` service in `compose.yaml` rebuilds `portal.css` on change |

If new styles do not appear, check that templates live under scanned paths and that the tailwind service is running (Docker path).

---

## `doc/`

| Path | Role |
|------|------|
| `doc/developer-guide/` | This guide |
| `doc/architecture/decisions/` | ADRs — link from guides; edit only via dedicated ADR PRs |

---

## Related

- [Getting started](getting-started.md)
- [Developer guide index](README.md)
- [Wagtail docs](https://docs.wagtail.org/)
