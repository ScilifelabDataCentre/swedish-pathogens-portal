# Swedish Pathogens Portal (Wagtail)

The Swedish Pathogens Portal is being rebuilt as a **Django + Wagtail** web application. This repository is the Wagtail-based portal (content management, page tree, StreamField blocks, and public site).

The live Swedish Pathogens Portal and the legacy codebase are in the [pathogens-portal repository](https://github.com/ScilifelabDataCentre/pathogens-portal).

---

## Technology stack

- **Backend:** Django
- **CMS:** Wagtail (page tree, StreamField, snippets, admin)
- **Database:** PostgreSQL
- **Package manager:** uv
- **Containerization:** Docker & Docker Compose

---

## Repository organization

The project uses a **single Wagtail app** (`cms/`) and a **Django project** package (`core/`). All page types, StreamField blocks, snippets, and CMS templates live under `cms/`.

| Folder | Purpose |
|--------|--------|
| **core/** | Django project: settings, root URLs, WSGI/ASGI, and overrides for Wagtail admin templates. No page models or CMS logic here. |
| **cms/** | Wagtail app: page models (`cms/pages/`), StreamField blocks (`cms/blocks/`), snippets (`cms/snippets/`), optional backend helpers (`cms/services/`), and templates/static for the public site. |
| **doc/** | Documentation and Architecture Decision Records (ADRs). |

**Semantics:**

- **core/** — Project configuration only. `cms/models.py` imports all page classes from `cms.pages` so Wagtail discovers them; you do not register pages in `core/`.
- **cms/pages/** — One Python file per page type (e.g. `home.py` → `HomePage`, `section_index.py` → `SectionIndexPage`). Each file defines a single `Page` subclass with `parent_page_types`, `subpage_types`, and `content_panels`. Add new page types here and export them in `cms/pages/__init__.py`.
- **cms/blocks/** — Reusable StreamField blocks; add new block classes here and export in `cms/blocks/__init__.py`. Block templates go under `cms/templates/cms/blocks/`.
- **cms/snippets/** — Wagtail snippets for reusable list-style content (e.g. notices, events). Use sub-pages for content that is a full page with its own URL.

**Example: adding a new page type**

1. Create `cms/pages/news_index.py` with a class that subclasses `wagtail.models.Page`, sets `template = "cms/pages/news_index.html"`, `parent_page_types = ["cms.HomePage"]`, `subpage_types = ["cms.StandardPage"]`, and defines `content_panels`.
2. In `cms/pages/__init__.py`, add `from .news_index import NewsIndexPage` and include `NewsIndexPage` in `__all__`.
3. Add `cms/templates/cms/pages/news_index.html` (extend your base template and override the content block).
4. Run `python manage.py makemigrations cms` and `python manage.py migrate`, then create the page in the Wagtail admin (Pages). No changes to `core/urls.py` are needed; Wagtail serves pages from the tree.

---

## Prerequisites

- Docker and Docker Compose
- Python 3.13+ (for local development without Docker)
- [uv](https://docs.astral.sh/uv/) (for local development)
- git

---

## Setup

All commands below assume you are in the project root.

### 1. Create a `.env` file

Copy the example and adjust if needed:

```bash
cp .env.example .env
```

### 2. Enable pre-commit hooks (optional but recommended)

The project uses [pre-commit](https://pre-commit.com/) for Ruff linting and formatting.

```bash
uv sync --group dev
uv run pre-commit install
```

To run hooks on all files:

```bash
uv run pre-commit run --all-files
```

### 3. Run the application

**With Docker (recommended)**

```bash
docker compose up
```

- **Site:** http://localhost:8000  
- **Wagtail admin:** http://localhost:8000/wagtail/

To run in the background:

```bash
docker compose up -d
```

**Without Docker (local)**

Ensure PostgreSQL is running (e.g. start only the DB with `docker compose up -d db`) and `.env` has correct `DATABASE_URL`. Then:

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Site at http://127.0.0.1:8000, Wagtail admin at http://127.0.0.1:8000/wagtail/.

**First-time login:** Create a superuser to access the Wagtail admin: `docker compose exec web python manage.py createsuperuser` (Docker) or `uv run python manage.py createsuperuser` (local).

---

## Development

### Migrations

Apply migrations:

```bash
docker compose exec web python manage.py migrate
```

Create migrations after changing models:

```bash
docker compose exec web python manage.py makemigrations cms
```

### Dependencies (uv)

Add a runtime dependency:

```bash
docker compose exec web uv add <package_name>
```

Add a dev dependency:

```bash
docker compose exec web uv add --group dev <package_name>
```

### Adding a new page type

1. Add a new module under `cms/pages/` (e.g. `cms/pages/news_index.py`) with your `Page` subclass.
2. Import and export it in `cms/pages/__init__.py`.
3. Add a template under `cms/templates/cms/pages/` (e.g. `news_index.html`).
4. Run `makemigrations cms` and `migrate`.
5. Create the page in the Wagtail admin (Pages).

No changes to `core/urls.py` are required; Wagtail serves pages from the page tree.

### Adding a new StreamField block

1. Define the block in `cms/blocks/` (e.g. in a new file or an existing one).
2. Export it in `cms/blocks/__init__.py`.
3. Add the block to the StreamField of the page model(s) that should use it.
4. Add a template under `cms/templates/cms/blocks/` if the block needs custom markup.
5. Run `makemigrations cms` and `migrate`.

---

## Project structure (summary)

```text
spp-wagtail/
├── core/                     # Django project (settings, urls, wsgi, admin overrides)
├── cms/                      # Wagtail CMS app
│   ├── pages/                # Page models (one file per page type)
│   ├── blocks/               # StreamField blocks
│   ├── snippets/             # Wagtail snippets
│   ├── services/             # Optional backend helpers
│   ├── templates/cms/        # Page and block templates
│   ├── static/cms/           # CSS, JS, images
│   └── migrations/
├── doc/
│   └── architecture/decisions/        # ADRs
├── manage.py
├── compose.yaml
├── Dockerfile
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## Tests and quality

- **Tests:** (WIP)
- **Linting/formatting:** Ruff via pre-commit and CI (see `.github/workflows/ruff.yaml`).

---

## Clearing Docker environment

To remove containers and images and start fresh:

```bash
docker compose down --rmi
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
