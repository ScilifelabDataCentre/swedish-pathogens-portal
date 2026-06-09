# Add a snippet

Snippets are **reusable records** managed under **Snippets** in Wagtail admin — not pages in the tree (no page URL).

Use snippets for site-wide or list-style data (navigation menus, announcements, dashboard upload metadata). Prefer a **page** when content needs its own URL (see [add a page type](add-a-page-type.md)).

**Example in repo:** `cms/snippets/site_announcement.py` → `SiteAnnouncement`.

---

## 1. Create the model

Add a file under `cms/snippets/`, e.g. `cms/snippets/callout_banner.py`:

```python
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet


class CalloutBanner(models.Model):
    title = models.CharField(max_length=255)
    message = RichTextField(features=["bold", "italic", "link"])
    is_enabled = models.BooleanField(default=False)

    panels = [
        FieldPanel("title"),
        FieldPanel("message", help_text="Shown on the public site when enabled."),
        FieldPanel("is_enabled"),
    ]

    class Meta:
        verbose_name = "Callout banner"

    def __str__(self) -> str:
        return self.title


class CalloutBannerViewSet(SnippetViewSet):
    model = CalloutBanner
    list_display = ["title", "is_enabled"]


register_snippet(CalloutBannerViewSet)
```

This project registers snippets via **`SnippetViewSet`** + `register_snippet(ViewSet)` (Wagtail 5+ pattern).

---

## 2. Export for discovery

In `cms/snippets/__init__.py`:

```python
from .callout_banner import CalloutBanner

__all__ = [
    # ...
    "CalloutBanner",
]
```

`cms/models.py` imports `cms.snippets` so models load at startup.

---

## 3. Use the snippet in the site

Typical patterns:

| Pattern | Example in repo |
|---------|-----------------|
| Template tag / context processor | `site_announcement` → `cms/templatetags/site_announcements.py` |
| Loaded in a view or `get_context` | Navigation → `navigation_menu.py` |
| Referenced from admin upload workflow | `dashboard_data.py` |

Wire your snippet where the public site or admin needs the data — snippets are not automatic; you add the read path in code.

---

## 4. Migrations

Snippet models are Django models — after adding fields:

```bash
docker compose exec web python manage.py makemigrations cms
docker compose exec web python manage.py migrate
```

Commit `cms/migrations/` changes.

---

## 5. Verify

- **Snippets** in admin shows the new type.
- Create a record and confirm the public behaviour (banner, menu, etc.) matches your wiring.

Add tests when rules must always hold (see `test_navigation_menu.py`, `test_site_announcement.py`).

---

## Related

- [Add a page type](add-a-page-type.md)
- [Add a StreamField block](add-a-streamfield-block.md)
- [Editor guide — snippets](../../editor-guide/README.md#docs-to-write-in-order)
