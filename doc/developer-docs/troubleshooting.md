# Troubleshooting

Common developer issues when working on `spp-wagtail`.

---

## Environment and `.env`

| Symptom | Check |
|---------|--------|
| `SECRET_KEY` / DB errors on start | [Getting started — `.env`](getting-started.md#environment-file-env); Docker uses `POSTGRES_HOST=db`, local uv uses `localhost` |
| Cannot connect to database | Postgres running? `docker compose ps` or local Postgres on port 5432 |
| Wrong settings module | Use `core.settings.development` (Docker/local dev) or `core.settings.test` for tests |

---

## Docker

| Symptom | Fix |
|---------|-----|
| Stale DB after migration changes | `docker compose down -v` then `docker compose up` and `migrate` |
| Code changes not visible | Rebuild if Dockerfile changed; otherwise volume mount should pick up edits |
| `web` exits on migrate error | Read container logs; fix migration conflict before retry |

See [Docker deployment](docker-deployment.md).

---

## Migrations

| Symptom | Likely cause |
|---------|----------------|
| `relation "cms_…" does not exist` but migrate shows nothing | Applied migration row out of sync with schema — team reset or surgical `django_migrations` fix |
| Merge conflicts in `cms/migrations/` | Keep both branches’ dependencies; run `makemigrations` if needed after resolving |

Policy: [operations — migrations](operations.md#migrations).

---

## Wagtail admin

| Symptom | Check |
|---------|--------|
| New page type not in “Add child” | `parent_page_types` / `subpage_types` on models; export in `cms/pages/__init__.py` |
| Empty header/footer menu | Navigation snippet **slug** must be `header` or `footer` — see [dev conventions](dev-conventions.md#wagtail-content-models) |
| Dashboard upload warning “no figures” | Slug not in `VIZ_MODULES` or viz module error — [add a dashboard](how-to-guides/add-a-dashboard.md) |
| StreamField block 500 on site | Template assumes fields the page type does not have — safe fallbacks in template or `get_context` |

---

## Tailwind CSS not updating

| Symptom | Fix |
|---------|-----|
| New utility classes have no effect | Templates must live under paths scanned by `@source` in `cms/static/cms/css/base.css` (`cms/`, `core/`) |
| Docker: CSS never rebuilds | Ensure `tailwind` service is running in `compose.yaml` |
| Local uv: no watch | Run Tailwind build manually per project README / Docker workflow |

After adding a new top-level app with templates, add an `@source` line — [PR #48](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/48).

---

## Tests

| Symptom | Fix |
|---------|-----|
| `NodeNotFoundError` for migrations | Test DB graph out of date — recreate test DB or run `migrate` with test settings |
| Wagtail `Site` / URL assertions fail | Ensure test sets default `Site` root to your `HomePage` — [testing — Wagtail patterns](testing.md#wagtail-test-patterns) |

---

## Related

- [Getting started](getting-started.md)
- [Operations](operations.md)
- [Testing](testing.md)
