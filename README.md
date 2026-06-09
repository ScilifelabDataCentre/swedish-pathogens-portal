# Swedish Pathogens Portal (Wagtail)

Django + Wagtail rebuild of the [Swedish Pathogens Portal](https://github.com/ScilifelabDataCentre/pathogens-portal) — page tree, StreamField blocks, snippets, dashboards, and the public site.

**Stack:** Django · Wagtail · PostgreSQL · uv · Docker

---

## Documentation

| Guide | |
|-------|---|
| **Developers** (setup, layout, contributing) | [doc/developer-guide/](doc/developer-guide/README.md) |
| **Architecture decisions** | [doc/architecture/decisions/](doc/architecture/decisions/) |

Wagtail admin help: [docs.wagtail.org](https://docs.wagtail.org/)

Start with [getting started](doc/developer-guide/01-getting-started.md) for `.env`, Docker, or local uv.

---

## Quick start (Docker)

From the repository root:

```bash
cp .env.example .env
# Set SECRET_KEY in .env — see doc/developer-guide/01-getting-started.md

docker compose up
```

| URL | |
|-----|---|
| Site | http://localhost:8000 |
| Wagtail admin | http://localhost:8000/wagtail/ |

First admin user: `docker compose exec web python manage.py createsuperuser`

More detail (uv, migrations, tests): [developer guide](doc/developer-guide/README.md).

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
