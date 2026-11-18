# Swedish Pathogens Portal

This is the repository for the [Swedish Pathogens Portal](https://www.pathogens.se), built using Django and Wagtail.

This replaces an earlier version of the portal, built using Hugo, which was live between June 2020 and October 2026 ([code for the Hugo version](https://github.com/ScilifelabDataCentre/pathogens-portal)). A [basic toolbox for a Pathogens Portal Node (PPN)](https://github.com/ScilifelabDataCentre/node-pathogens-portal), also built in Hugo, remains available for others to be able to initiate a PPN for their community.

**Stack:** Django · Wagtail · PostgreSQL · uv · Docker

---

## Documentation

| Guide | |
|-------|---|
| **Developer docs** (setup, layout, how-tos) | [doc/developer-docs/](doc/developer-docs/README.md) |
| **Architecture decisions** | [doc/architecture/decisions/](doc/architecture/decisions/) |

Wagtail admin help: [docs.wagtail.org](https://docs.wagtail.org/)

Start with [getting started](doc/developer-docs/getting-started.md) for `.env`, Docker, or local uv.

---

## Quick start (Docker)

From the repository root:

```bash
cp .env.example .env
# Set SECRET_KEY in .env — see doc/developer-docs/getting-started.md

docker compose up
```

| URL | |
|-----|---|
| Site | http://localhost:8000 |
| Wagtail admin | http://localhost:8000/wagtail/ |

First admin user (after the stack is up):

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

More detail (uv, email/Mailpit, migrations, tests): [developer documentation](doc/developer-docs/README.md).

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
