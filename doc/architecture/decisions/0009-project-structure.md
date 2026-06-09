# 9. Project structure and code organisation

**Date**: 2026-06-09

## Status

Accepted

## Related ADRs

- [0002 – Project migration from Hugo implementation to Python architecture](0002-project-migration-from-hugo-to-python.md)
- [0003 – Formatting Rules](0003-formatting-rules.md)
- [0006 – Adopt Wagtail as Content Management System](0006-adopt-wagtail-as-cms.md)

## Context

Following the decision to rebuild the Swedish Pathogens Portal in a Wagtail-first fashion (ADR-0006), the codebase needs a documented, consistent organisation. Without one, content types, components, templates, and supporting logic tend to drift into ad-hoc locations.

A clear structure provides:

- **Predictable navigation:** every page, snippet, block, or piece of domain logic has one obvious location.
- **A repeatable extension path:** adding a new content type follows the same steps every time.
- **Reviewable diffs:** small, isolated files keep pull requests easy to read.

The structure may still change slightly as the portal matures. This ADR records the **initial agreed organisation** rather than a frozen, exhaustive file inventory. The directory responsibilities and conventions below are the normative part, while individual file names are illustrative.

## Decision

We adopt a single local Django app, `cms`, that contains all Wagtail content models and their supporting components, alongside an environment-agnostic `core` project package and a small number of plain Python packages for non-CMS domain logic.

### Directory layout

```text
spp-wagtail/
├── core/                       # Django project configuration (no content models)
│   ├── settings/
│   │   ├── base.py             # Environment-agnostic settings shared by all environments
│   │   ├── development.py      # Local development overrides
│   │   ├── production.py       # Production overrides
│   │   └── test.py             # Test settings (SQLite in-memory, fast password hasher)
│   ├── templates/
│   │   └── wagtailadmin/       # Wagtail admin template overrides (branding, login)
│   ├── urls.py                 # Root URLconf
│   ├── views.py                # Project-wide views (e.g. healthz)
│   └── wsgi.py                 # WSGI entry point
├── cms/                        # The single local app: all Wagtail content + components
│   ├── pages/                  # Wagtail Page models (one class per file)
│   ├── snippets/               # Wagtail snippets (one class per file)
│   ├── blocks/                 # StreamField StructBlocks (one class per file)
│   ├── forms/                  # Django / Wagtail forms
│   ├── views/                  # Non-Wagtail views (e.g. htmx partial endpoints)
│   ├── services/               # Reusable domain logic and helpers
│   ├── handlers/               # Rich-text feature handlers
│   ├── templatetags/           # Custom template tags
│   ├── templates/cms/          # base/header/footer/404 + pages/ blocks/ components/ admin/
│   ├── static/cms/             # Static assets: css/ js/ images/
│   ├── tests/                  # Unit tests (test_<feature>.py) + shared utils.py
│   ├── migrations/             # Generated migrations
│   ├── models.py               # Registration shim: star-imports pages + snippets
│   ├── apps.py                 # AppConfig
│   ├── urls.py                 # Non-Wagtail URL patterns (htmx endpoints)
│   ├── wagtail_hooks.py        # Wagtail hooks (e.g. register rich-text features)
│   └── image_formats.py        # Custom rich-text image formats
├── dashboard_visualisation/    # Supporting package (NOT a Django app)
│   ├── registry.py             # Visualisation registry
│   └── utils/                  # plotly.py, uploads.py
├── portal_data/                # Supporting package (NOT a Django app)
│   ├── context.py
│   ├── services.py
│   ├── views.py
│   └── tests/
├── doc/architecture/decisions/ # Architecture Decision Records
├── manage.py                   # Django CLI entry point
├── pyproject.toml, uv.lock     # Dependencies (managed by uv)
├── compose.yaml, Dockerfile, prod-entrypoint.sh   # Container + production startup
└── README.md, LICENSE, CITATION.cff, renovate.json
```

### The `cms` application

`cms` is the only entry in `LOCAL_APPS` (see `core/settings/base.py`). It is divided into single-responsibility subpackages:

- **`pages/`** — Wagtail `Page` subclasses (e.g. `home`, `standard_page`, `section_index`, the index/detail pairs for topics, news, outbreaks, PLP, and highlights & editorials, plus `dashboard`, `catalogue`, `portal_data`). Canonical example: `cms/pages/standard_page.py`.
- **`snippets/`** — reusable, non-page content registered with `@register_snippet` (e.g. `navigation_menu`, `plp_category`, `site_announcement`, `dashboard_data`). Canonical example: `cms/snippets/navigation_menu.py`.
- **`blocks/`** — `StreamField` `StructBlock`, each with a `Meta.template` (e.g. `cards`, `alerts`, `collapsible`, `data_table`, `plotly_figure`, `static_figure`, `last_updated`). Canonical example: `cms/blocks/cards.py`.
- **`forms/`** — Django / Wagtail form classes used by pages and views.
- **`views/`** — plain Django views for endpoints that Wagtail does not serve, primarily htmx partials (e.g. `data_table`).
- **`services/`** — reusable domain logic and helpers kept out of models and views (e.g. `validators`, `decorators`, `data_table`, `highlights_and_editorials`).
- **`handlers/`** — Wagtail rich-text feature handlers (e.g. `ExternalLinkNewTabHandler`).
- **`templatetags/`** — custom template tags (e.g. `navigation_menu`, `plotly_js`, `site_announcements`).
- **`templates/cms/`** — site templates: shared `base.html`, `header.html`, `footer.html`, `404.html`, with `pages/`, `blocks/`, `components/`, and `admin/` subdirectories.
- **`static/cms/`** — `css/` (Tailwind input plus the generated, git-ignored `portal.css`), `js/`, and `images/`.
- **`tests/`** — unit tests named `test_<feature>.py` mirroring the components they cover, plus a shared `utils.py`.

The app-level module files glue the subpackages to Django and Wagtail:

- **`models.py`** is a thin registration shim — it only re-exports the page and snippet packages so Django/Wagtail discover the models:

```python
from cms.pages import *  # noqa: F403
from cms.snippets import *  # noqa: F403
```

- **`urls.py`** holds only non-Wagtail URL patterns (htmx endpoints), namespaced under `app_name = "cms"`.
- **`wagtail_hooks.py`** registers Wagtail hooks (e.g. rich-text features).
- **`image_formats.py`** registers custom rich-text image formats.
- **`apps.py`** is the standard `AppConfig`.

### Supporting packages

`dashboard_visualisation/` and `portal_data/` are plain Python packages, **not** Django apps — they are absent from `INSTALLED_APPS`. They hold domain logic that backs specific page types (dashboard rendering and portal-data handling respectively) but is not itself Wagtail content. Keeping them outside `cms` separates CMS content models from data/visualisation concerns.

### `core` and URL ownership

`core` contains only project configuration: a split settings package (`base`/`development`/`production`/`test`), the root URLconf, project-wide views such as `healthz`, the WSGI entry point, and Wagtail admin template overrides under `core/templates/wagtailadmin/`.

Wagtail owns content URLs. `core/urls.py` mounts only the Django admin, `healthz`, the Wagtail admin, the `cms/` htmx routes, and finally the Wagtail page catch-all (`wagtail.urls`).
Content pages are routed by Wagtail's page tree, not by hand-written URL patterns.

### Conventions

- **One class per file + barrel exports.** Each page, snippet, and block lives in its own module. The package `__init__.py` imports it and lists it in an explicit `__all__`. New components are added by: create the file, re-export it from the package `__init__.py`, reference/register it where it is used, and add a test.
- **Centralised model registration.** `cms/models.py` only star-imports the `pages` and `snippets` packages. Models are never defined there directly.
- **Naming.** File names use `lower_snake_case`. URL paths use `lower-kebab-case` (ADR-0003).
- **Settings split.** Environment-agnostic configuration lives in `core/settings/base.py`. Environment-specific overrides live in the sibling settings modules.

## Consequences

### Positive

- Each content type or component has one obvious location, making the codebase easy to navigate for newcomers and agents alike.
- One class per file keeps diffs small and isolated, simplifying code review.
- The `models.py` shim keeps Django/Wagtail model discovery working while models stay in their per-type packages.
- Presentation (`templates/`, `static/`), domain logic (`services/`), and content models (`pages/`, `snippets/`, `blocks/`) are clearly separated.

### Negative

- More files and barrel `__init__.py` modules increase boilerplate and maintenance.
- Forgetting to re-export a class from a package `__init__.py` causes the page, snippet, or block to silently fail to register or import.
- Domain logic for some features spans two locations (`cms` plus a supporting package such as `dashboard_visualisation` or `portal_data`).
- The structure is enforced by convention and review rather than tooling.

### Mitigation

- Keep `cms/models.py` as a thin star-import shim so registration stays centralised and predictable.
- Update `README.md` to reference this ADR and remove its stale structure description.
- Treat this ADR as living documentation and revise it as the structure evolves.
