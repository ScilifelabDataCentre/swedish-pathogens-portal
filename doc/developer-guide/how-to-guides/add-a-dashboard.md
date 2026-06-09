# Add a dashboard

Add a **new data dashboard** to the portal. Most dashboards reuse the existing `DashboardPage` and `DashboardIndexPage` — you add a **visualisation module** and register its slug. Editors then create the page, upload CSV data, and wire `plotly_figure` blocks.

**Before you start:** Read [repository tour — backend services](../repository-tour.md) and [ADR-0004](../../architecture/decisions/0004-visualisation-tool-for-dashboards.md) (Plotly). You rarely need a new page model.

**Examples in repo:** `cms/pages/dashboard.py`, `cms/snippets/dashboard_data.py`, `dashboard_visualisation/registry.py`, test pattern in `cms/tests/sample_viz.py`.

---

## How the pieces connect

```text
dashboard_visualisation/<module>.py   CSV → Plotly JSON (on upload)
         ↓ registered by slug
DashboardData snippet (admin upload)   stores CSV + JSON in `data`
         ↓ matched by dashboard_slug == page slug
DashboardPage (Wagtail tree)           StreamField: text, plotly_figure, …
         ↓
Public URL under DashboardIndexPage    /dashboards/<slug>/
```

**Slug contract (critical):** these three must use the **same** slug string (e.g. `serology-statistics`):

| Place | Field / key |
|-------|-------------|
| `DashboardPage` | page `slug` (set when editor creates the page) |
| `DashboardData` snippet | `dashboard_slug` |
| `dashboard_visualisation/registry.py` | key in `VIZ_MODULES` |

**Figure contract:** `generate_figures()` returns `dict[figure_id, plotly_json]`. Each `plotly_figure` block on the page uses a `figure_id` that exists in that dict.

---

## Create the visualisation module

Add one Python module under `dashboard_visualisation/`, e.g. `dashboard_visualisation/serology_statistics.py`:

```python
from typing import Any

import plotly.express as px

from dashboard_visualisation.utils import figure_to_json
from dashboard_visualisation.utils.uploads import SourceFile, read_csv_dataframe, rewind_source_file

REQUIRED_SOURCE_COLUMNS = frozenset({"date", "value"})


def validate_source_columns(columns: list[str]) -> str | None:
    """Return an error message when required CSV columns are missing."""
    found = {column.strip() for column in columns}
    if not REQUIRED_SOURCE_COLUMNS.issubset(found):
        return f"CSV must include columns: date, value (found: {', '.join(columns)})."
    return None


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Read CSV and return all Plotly figures for this dashboard."""
    rewind_source_file(source_file)
    data = read_csv_dataframe(source_file)
    fig = px.bar(data, x="date", y="value")
    return {
        "monthly_counts": figure_to_json(fig),
        # add more figure_id keys as needed
    }
```

- **`generate_figures`** — required; returns all figures for the dashboard in one call.
- **`validate_source_columns`** — optional; rejects bad CSV in admin before save.
- Use **`figure_to_json`** so NaN/Inf values are safe for PostgreSQL JSONB.
- Call **`rewind_source_file`** before reading (upload code may have read the file already).

Reference implementation for tests only: `cms/tests/sample_viz.py`.

---

## Register the slug

In `dashboard_visualisation/registry.py`, add to `VIZ_MODULES`:

```python
VIZ_MODULES: dict[str, str] = {
    "serology-statistics": "dashboard_visualisation.serology_statistics",
}
```

Without a registry entry, CSV upload succeeds but figure generation returns `{}` and admin shows a warning.

---

## Tests

Add tests for the viz module and registry dispatch. Patterns:

```bash
uv run python manage.py test cms.tests.test_dashboard_data_upload cms.tests.test_dashboard_page --settings core.settings.test
```

- Register your module in tests with `patch.dict(VIZ_MODULES, …)` (see `test_dashboard_data_upload.py`).
- Assert `generate_figures` returns expected `figure_id` keys and valid JSON shape.
- Test `validate_source_columns` when you define it.

---

## Editor steps (after your code is deployed)

No developer migration is needed for viz-only changes. Editors:

1. **Pages** → **Dashboards** (`DashboardIndexPage`) → **Add child page** → **Dashboard page**.
   - Set **slug** to match `VIZ_MODULES` (e.g. `serology-statistics`).
   - Fill **card details** (description, image), **data status** (`active` or `historic`), and **content** StreamField.
2. **Snippets** → **Dashboard Data Upload** → add row with the same **dashboard slug**.
   - Upload **CSV** (export from Excel/Numbers as CSV — `.xlsx` / `.numbers` are rejected).
   - On save, figures regenerate into the `data` JSON field.
3. On the dashboard page, add **`plotly_figure`** blocks with `figure_id` values from your `generate_figures` output.
   - Optional: `last_updated` block (reads `data_updated_at` from snippet), `text`, `alert`, `static_figure`.

The index at `/dashboards/` lists child pages grouped by `data_status` (`active` / `historic`).

---

## Historic dashboards (no live CSV pipeline)

For dashboards that no longer receive updates:

- Set page **data status** to `historic`.
- In the snippet, paste Plotly JSON directly into the **`data`** field (or upload a one-off CSV if a viz module still exists).
- `VIZ_MODULES` registration is optional if figures are maintained manually.

---

## When you need more than a viz module

| Need | Action |
|------|--------|
| New chart on existing dashboard | Add `figure_id` in `generate_figures`; editor adds block |
| New dashboard URL | Viz module + registry + editor creates `DashboardPage` (no new page class) |
| New fields on every dashboard | Change `DashboardPage` in `cms/pages/dashboard.py` + migration |
| Custom index layout | Change `DashboardIndexPage` / `dashboard_index.html` |

---

## Checklist

- [ ] `dashboard_visualisation/<name>.py` with `generate_figures`
- [ ] Optional `validate_source_columns` for CSV schema
- [ ] Slug registered in `VIZ_MODULES`
- [ ] Tests for figure output and column validation
- [ ] Document `figure_id` keys for editors (PR description or ticket)
- [ ] Editor: page slug, snippet slug, and blocks aligned

---

## Related

- [Repository tour](../repository-tour.md)
- [Add a StreamField block](add-a-streamfield-block.md) — `PlotlyFigureBlock` lives in `cms/blocks/plotly_figure.py`
- [Add a snippet](add-a-snippet.md) — `DashboardData` pattern
- [ADR-0004 — Plotly](../../architecture/decisions/0004-visualisation-tool-for-dashboards.md)
- [ADR-0007 — Data hosting](../../architecture/decisions/0007-data-hosting-architecture.md)
