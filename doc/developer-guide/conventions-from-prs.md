# Conventions from PR reviews

Short rules distilled from merged PRs and team reviews. For full ADR detail see [ADR-0003](../architecture/decisions/0003-formatting-rules.md) (formatting, Ruff) and [ADR-0006](../architecture/decisions/0006-adopt-wagtail-as-cms.md) (Wagtail).

---

## Pull requests

- **Title:** `FREYA-XXXX: Short description` (see [PR template](../../.github/pull_request_template.md)).
- **Description:** Link the Jira issue; note migrations, manual test steps, and anything reviewers should verify in admin.
- **CI:** [Ruff](../../.github/workflows/ruff.yaml) lint and format must pass (`uv run ruff check .`, `uv run ruff format --check .`).
- **Model changes:** Run `makemigrations cms`, commit the migration, and run tests for the area you changed.
- **Migrations after first deploy:** Append-only — add `0002_…`, `0003_…`. Do not rewrite `0001_initial.py` once it has been applied anywhere; teammates will see “No migrations to apply” while tables are missing.

---

## Layout and naming

- **One page type per file** under `cms/pages/` (e.g. `news.py`, `catalogue.py`). See [add a page type](04-how-to-guides/add-a-page-type.md).
- **Blocks** in `cms/blocks/`; **snippets** in `cms/snippets/`; shared logic in `cms/services/`.
- **File names:** lowercase with underscores ([ADR-0003](../architecture/decisions/0003-formatting-rules.md)).

---

## Wagtail content models

- **`RichTextBlock`:** Pass an explicit `features=[...]` allowlist. Omitting `features` falls back to Draftail defaults (often wider than intended). Add new capabilities (e.g. `"image"`) by name, not by loosening to defaults.

  ```python
  blocks.RichTextBlock(
      features=["h2", "h3", "bold", "italic", "link", "ol", "ul"],
  )
  ```

- **`help_text`:** Use on fields, block `Meta`, and panels so admin behaviour matches what templates expect (especially blocks that depend on page-type fields not yet on every model).
- **Child-page listing blocks:** Templates must not assume every `Page` has custom fields (e.g. `thumbnail`, `description`). Use `search_description`, concrete page properties, or safe fallbacks in `get_context`.
- **Navigation snippets:** Menu **slug** must match what templates pass to `get_menu` (`"header"`, `"footer"`). Document this in snippet `help_text`; a mismatch returns an empty menu with only a log warning.

---

## Shared services (filters and HTMX)

Catalogue and highlights index pages share filter validation and HTMX partial rendering ([PR #46](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/46)).

- **`validate_filters`** — `cms/services/validators.py`. Pass `expected_keys` for the page (catalogue: `{"search", "type"}`; highlights: default all three). Invalid query params raise `Http404`.
- **`@htmx_request_with_url_update()`** — `cms/services/decorators.py`. Decorating `serve` requires a class attribute:

  ```python
  htmx_template = "cms/components/catalogue_list.html#catalogue_grid"

  @htmx_request_with_url_update()
  def serve(self, request, *args, **kwargs):
      return super().serve(request, *args, **kwargs)
  ```

- **Tests:** Prefer unit tests on `validators` and `decorators` when logic is extracted; add a template render test when a block can 500 on generic pages.

---

## Typing

At empty collection init sites, annotate the variable ([PR #49](https://github.com/ScilifelabDataCentre/spp-wagtail/pull/49)):

```python
cards: list[dict[str, Any]] = []
all_dashboards: dict[str, PageQuerySet] = {}
```

Match key types to what you actually store (`int` FK ids vs `str`). Prefer precise return types on shared helpers (e.g. `validate_filters` → `dict[str, str | list[str]]`) over `Any`. Ruff ANN rules apply per [ADR-0003](../architecture/decisions/0003-formatting-rules.md).

---

## Frontend (Tailwind)

- **`@source`** in `cms/static/cms/css/base.css` must include paths where Tailwind classes appear (`cms/`, `core/`). Add another `@source` line when you add a new top-level app with templates.
- **DaisyUI:** Keep `@source not` guards for generated `daisyui*.mjs` files (see comments in `base.css`).

---

## Tests

```bash
uv run python manage.py test cms.tests --settings core.settings.test
```

Run the module you touched (e.g. `cms.tests.test_card_blocks`). Model-only tests do not cover admin `Form.clean()` rules — extract validators or add form tests when validation is critical.

---

## Related

- [Developer guide index](README.md)
- [How-to guides](04-how-to-guides/)
- Local review notes (not in repo): parent `doc/PR-Reviews/` on the documentation branch workspace
