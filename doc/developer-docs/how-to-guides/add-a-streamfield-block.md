# Add a StreamField block

Reusable content units editors add inside a page **StreamField** (e.g. on `StandardPage`).

**Example in repo:** `cms/blocks/alerts.py` → `AlertBlock` → `cms/templates/cms/blocks/alert.html`.

---

## Define the block

Add a class in `cms/blocks/` (new file or existing module), usually a `StructBlock`:

```python
from wagtail import blocks


class CalloutBlock(blocks.StructBlock):
    body = blocks.RichTextBlock(
        features=["bold", "italic", "link"],
        help_text="Short callout text.",
    )

    class Meta:
        icon = "openquote"
        label = "Callout"
        help_text = "Highlighted short text."
        template = "cms/blocks/callout.html"
```

- Use explicit `features=` on `RichTextBlock` (see `AlertBlock`).
- Set `help_text` on fields and in `Meta` for editors.

---

## Export the block

In `cms/blocks/__init__.py`:

```python
from .callout import CalloutBlock

__all__ = [
    # ...
    "CalloutBlock",
]
```

---

## Add a template

Create `cms/templates/cms/blocks/callout.html`:

```django
{% load wagtailcore_tags %}
<div class="callout">
    {% include_block value.body %}
</div>
```

`Meta.template` must match this path.

---

## Use on a page model

Add the block to a page’s `StreamField` in `cms/pages/`:

```python
content = StreamField(
    [
        ("text", blocks.RichTextBlock(...)),
        ("callout", CalloutBlock()),
    ],
    blank=True,
)
```

Then run `makemigrations cms` and `migrate` (model field changed).

---

## Verify

- Create or edit a page with that StreamField in Wagtail admin — block appears in the picker.
- Publish and check the public template renders correctly.

Optional: add tests under `cms/tests/` (see `test_alert_block.py`).

---

## Related

- [Add a page type](add-a-page-type.md)
- [Add a snippet](add-a-snippet.md)
