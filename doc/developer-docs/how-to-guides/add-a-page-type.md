# Add a page type

Steps to add a new Wagtail page type. Public URLs come from the page tree — you do not register routes in `core/urls.py`.

**Before you start:** Prefer a [sub-page](https://docs.wagtail.org/en/stable/getting_started/creating_pages.html) under an index if the content has its own URL. Use a snippet only for small reusable records without a page (see [repository tour](../repository-tour.md)).

---

## Choose parent and children

On your page class set:

```python
parent_page_types = ["cms.HomePage"]      # allowed parents
subpage_types = ["cms.YourDetailPage"]    # allowed children (or [] for none)
```

Optional: `max_count = 1` if only one instance should exist (e.g. `NewsIndexPage`).

**Examples in repo:** `standard_page.py` (no children), `news_index.py` / `news.py` (index + detail).

---

## Create the page model

Add **one file** under `cms/pages/`, e.g. `cms/pages/event.py`:

```python
from wagtail.admin.panels import FieldPanel
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock


class EventPage(Page):
    template = "cms/pages/event.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []

    content = StreamField([("alert", AlertBlock())], blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("content"),
    ]
```

- Set `template` to a path under `cms/templates/cms/pages/`.
- Add fields, `StreamField`, and `content_panels` (use `help_text` for editors).
- Override `get_context()` only when the template needs extra data (see `news_index.py`).

---

## Register the model

In `cms/pages/__init__.py`:

```python
from .event import EventPage

__all__ = [
    # ...existing exports...
    "EventPage",
]
```

`cms/models.py` imports `cms.pages` — no change needed there.

---

## Add a template

Create `cms/templates/cms/pages/event.html`:

```django
{% extends "cms/base.html" %}
{% load wagtailcore_tags %}

{% block content %}
{% include_block page.content %}
{% endblock %}
```

Match patterns in `standard_page.html` or `news_index.html` as needed.

---

## Migrations

```bash
# Docker
docker compose exec web python manage.py makemigrations cms
docker compose exec web python manage.py migrate

# Local uv
uv run python manage.py makemigrations cms
uv run python manage.py migrate
```

Commit new files under `cms/migrations/`.

---

## Create the page in admin

**Pages** → choose parent → **Add child page** → your new type → fill fields → publish.

Wagtail only lists types allowed by `parent_page_types` / `subpage_types`.

---

## Tests (recommended)

Add or extend `cms/tests/test_<area>_pages.py`. Use helpers from `cms/tests/utils.py` to build a page tree, then assert the public URL or context.

```bash
uv run python manage.py test cms.tests.test_news_pages --settings core.settings.test
```

---

## Checklist

- [ ] One class per file in `cms/pages/`
- [ ] Exported in `cms/pages/__init__.py`
- [ ] Template under `cms/templates/cms/pages/`
- [ ] Migrations created and committed
- [ ] Page creatable in admin under intended parent
- [ ] Tests for non-trivial `get_context` or validation

---

## Related

- [Repository tour](../repository-tour.md)
- [Add a StreamField block](add-a-streamfield-block.md)
- [Add a snippet](add-a-snippet.md)
- [Add a dashboard](add-a-dashboard.md)
- [ADR-0006 — Wagtail](../../architecture/decisions/0006-adopt-wagtail-as-cms.md)
