# Testing

How we run and write tests for `spp-wagtail`.

---

## What we test

- **Unit / service logic** — validators, decorators, viz modules, portal data helpers.
- **Models and snippets** — constraints, `clean()`, `get_context` where behaviour matters.
- **Wagtail pages** — parent/child rules, public URLs, template context.
- **Template tags and handlers** — e.g. navigation menu, external link handler.

We use Django’s `TestCase` and `wagtail.test.utils.WagtailPageTestCase`. Settings: `core.settings.test`.

---

## Running tests

### Local (uv)

```bash
uv run python manage.py test cms.tests --settings core.settings.test
```

Single module or class:

```bash
uv run python manage.py test cms.tests.test_dashboard_page --settings core.settings.test
uv run python manage.py test cms.tests.test_validators.TestValidateFilters --settings core.settings.test
```

### Docker

```bash
docker compose exec web python manage.py test cms.tests --settings core.settings.test
```

### CI

GitHub Actions runs Ruff on push and PR. Run locally before opening a PR — see [operations — CI](operations.md#ci-and-quality).

`core/settings/test.py` extends base settings with Wagtail admin URL constants. Always pass `--settings core.settings.test`.

### What to run for your change

| You changed | Run at least |
|-------------|--------------|
| Page model | `cms.tests.test_<area>_pages` or add tests there |
| Snippet / upload | Matching `test_*` module (e.g. `test_dashboard_data_upload`) |
| `cms/services/` | `test_validators`, `test_decorators`, or new module tests |
| Viz module | `test_dashboard_data_upload` (registry dispatch) + module unit tests |
| Template tag | Dedicated `test_*` for the tag |

---

## Wagtail test patterns

### Page tree setup

Many tests build a minimal tree: root → `HomePage` → index → detail. Example: `cms/tests/test_dashboard_page.py`.

```python
from wagtail.models import Page, Site
from cms.pages.home import HomePage

root = Page.get_first_root_node()
home = HomePage(title="Home", slug="home")
root.add_child(instance=home)
Site.objects.update_or_create(
    is_default_site=True,
    defaults={"hostname": "testserver", "root_page": home},
)
```

Publish when the public URL or `live()` queryset matters: `page.save_revision().publish()`.

### Helpers

`cms/tests/utils.py`:

- **`create_test_image()`** — Wagtail image for page/block tests that need thumbnails.
- **`validate_csv()`** — re-export of dashboard CSV validation (shared with upload tests).

### Snippet and form tests

- Model tests can create rows directly (`NavigationMenu.objects.create(...)`).
- Admin `Form.clean()` rules may need separate tests or extracted validators — model tests alone do not cover InlinePanel formsets.

### Registry and patches

Dashboard viz tests register a fake module without polluting production registry:

```python
from unittest.mock import patch
from dashboard_visualisation.registry import VIZ_MODULES

with patch.dict(VIZ_MODULES, {"sample-dashboard": "cms.tests.sample_viz"}):
    ...
```

See `cms/tests/test_dashboard_data_upload.py` and `cms/tests/sample_viz.py`.

### Template tag smoke tests

Render a minimal Django template string with `Template` / `Context` and assert output — see `test_navigation_menu.py` (`GetMenuTemplateTagTest`).

---

## Related

- [Developer conventions — tests](dev-conventions.md#tests)
- [Troubleshooting — test issues](troubleshooting.md#tests)
- [How-to: page type — tests](how-to-guides/add-a-page-type.md#tests-recommended)
