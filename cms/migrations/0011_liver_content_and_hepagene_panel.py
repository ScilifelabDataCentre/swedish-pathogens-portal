"""Add liver_content, copy from content, insert HepageniePanel (Approach B cut-over)."""

from __future__ import annotations

import uuid
from typing import Any

import django.core.validators
import wagtail.fields
from django.db import migrations


def copy_parent_content_to_liver_content(apps, schema_editor):
    """Copy DashboardPage.content into liver_content (page rows + revisions)."""
    Liver = apps.get_model("cms", "LiverResourceDashboardPage")
    Revision = apps.get_model("wagtailcore", "Revision")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for liver in Liver.objects.all().iterator():
        parent = liver.dashboardpage_ptr
        Liver.objects.filter(pk=liver.pk).update(liver_content=parent.content)

    try:
        ct = ContentType.objects.get(app_label="cms", model="liverresourcedashboardpage")
    except ContentType.DoesNotExist:
        return

    for revision in Revision.objects.filter(content_type=ct).iterator():
        data = revision.content
        if not isinstance(data, dict):
            continue
        if "liver_content" in data and data["liver_content"]:
            continue
        if "content" not in data:
            continue
        data["liver_content"] = data["content"]
        revision.content = data
        revision.save(update_fields=["content"])


def noop_reverse(apps, schema_editor):
    """Keep data on reverse; schema reverse drops the AddField column."""


_PANEL_TYPE = "hepagene_panel"


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("type", ""))
    return str(getattr(block, "block_type", ""))


def _as_raw_list(stream: Any) -> list[dict[str, Any]]:
    """Normalize StreamField value to JSON-serializable raw block dicts."""
    if stream is None:
        return []
    if isinstance(stream, str):
        import json

        stream = json.loads(stream)
    # StreamValue.raw_data is already JSON-safe (strings, not RichText).
    raw_data = getattr(stream, "raw_data", None)
    if raw_data is not None:
        return [
            {
                "type": item["type"],
                "value": item["value"],
                "id": item.get("id") or str(uuid.uuid4()),
            }
            for item in raw_data
        ]
    raw: list[dict[str, Any]] = []
    for block in stream:
        if isinstance(block, dict):
            raw.append(
                {
                    "type": block["type"],
                    "value": block.get("value"),
                    "id": block.get("id") or str(uuid.uuid4()),
                }
            )
            continue
        child_raw = getattr(block, "raw_data", None)
        if isinstance(child_raw, dict):
            raw.append(
                {
                    "type": child_raw.get("type", _block_type(block)),
                    "value": child_raw.get("value"),
                    "id": child_raw.get("id") or str(uuid.uuid4()),
                }
            )
            continue
        raise TypeError(
            f"Cannot JSON-serialize StreamField block of type {_block_type(block)!r}; "
            "expected raw dict or StreamValue.raw_data"
        )
    return raw


def _insert_index(stream: list[dict[str, Any]]) -> int:
    """Index after leading text(s) + optional alert + collapsible(s).

    Matches Approach B default above-panel layout so later text blocks
    (downloads, cite) stay below the panel.
    """
    index = 0
    n = len(stream)
    while index < n and _block_type(stream[index]) == "text":
        index += 1
    if index < n and _block_type(stream[index]) == "alert":
        index += 1
    while index < n and _block_type(stream[index]) == "collapsible":
        index += 1
    return index


def _insert_panel(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(_block_type(block) == _PANEL_TYPE for block in stream):
        return stream
    index = _insert_index(stream)
    panel = {"type": _PANEL_TYPE, "value": {}, "id": str(uuid.uuid4())}
    return stream[:index] + [panel] + stream[index:]


def insert_hepagene_panel(apps, schema_editor):
    """Place one panel after leading text + alert + collapsible(s)."""
    Liver = apps.get_model("cms", "LiverResourceDashboardPage")
    Revision = apps.get_model("wagtailcore", "Revision")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for liver in Liver.objects.all().iterator():
        updated = _insert_panel(_as_raw_list(liver.liver_content))
        Liver.objects.filter(pk=liver.pk).update(liver_content=updated)

    try:
        ct = ContentType.objects.get(app_label="cms", model="liverresourcedashboardpage")
    except ContentType.DoesNotExist:
        return

    for revision in Revision.objects.filter(content_type=ct).iterator():
        data = revision.content
        if not isinstance(data, dict) or "liver_content" not in data:
            continue
        data["liver_content"] = _insert_panel(_as_raw_list(data.get("liver_content")))
        revision.content = data
        revision.save(update_fields=["content"])




class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0010_alter_liverresourcedashboardpage_hepagene"),
    ]

    operations = [
        migrations.AddField(
            model_name='liverresourcedashboardpage',
            name='liver_content',
            field=wagtail.fields.StreamField([('text', 0), ('alert', 3), ('collapsible', 15), ('data_table', 13), ('last_updated', 18), ('plotly_figure', 25), ('static_figure', 30), ('hepagene_panel', 31)], block_lookup={0: ('wagtail.blocks.RichTextBlock', (), {}), 1: ('wagtail.blocks.RichTextBlock', (), {'features': ['h4', 'h5', 'bold', 'italic', 'link'], 'help_text': 'Alert body. Rich text only: headings H4–H5, bold, italic, and links.'}), 2: ('wagtail.blocks.ChoiceBlock', [], {'choices': [('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'), ('error', 'Error')], 'help_text': 'Controls the visual style (colour) of the alert on the public site.'}), 3: ('wagtail.blocks.StructBlock', [[('message', 1), ('alert_type', 2)]], {}), 4: ('wagtail.blocks.CharBlock', (), {'help_text': 'Title shown in the always-visible summary line.', 'max_length': 255, 'required': True}), 5: ('wagtail.blocks.CharBlock', (), {'help_text': 'Unique identifier for this table on the page (letters, numbers, hyphens). Defaults to a slugified version of the table caption.', 'max_length': 60, 'required': False, 'validators': [django.core.validators.RegexValidator('^[a-zA-Z0-9-]*$', 'Only letters, numbers, and hyphens.')]}), 6: ('wagtail.blocks.BooleanBlock', (), {'default': False, 'help_text': 'Show search, pagination, and per-page controls.', 'required': False}), 7: ('wagtail.blocks.ChoiceBlock', [], {'choices': [('10', '10'), ('25', '25'), ('50', '50')], 'help_text': 'Number of rows per page when controls are visible (display all entries if controls are not shown).', 'required': False}), 8: ('wagtail.blocks.CharBlock', (), {}), 9: ('wagtail.blocks.RichTextBlock', (), {'features': ['bold', 'italic', 'link']}), 10: ('wagtail.blocks.FloatBlock', (), {}), 11: ('wagtail.blocks.IntegerBlock', (), {}), 12: ('wagtail.contrib.typed_table_block.blocks.TypedTableBlock', [[('text', 8), ('rich_text', 9), ('numeric', 10), ('integer', 11)]], {}), 13: ('wagtail.blocks.StructBlock', [[('table_id', 5), ('show_controls', 6), ('per_page', 7), ('table', 12)]], {}), 14: ('wagtail.blocks.StreamBlock', [[('text', 0), ('data_table', 13)]], {'help_text': 'Inner content revealed when the section is opened.', 'min_num': 1}), 15: ('wagtail.blocks.StructBlock', [[('label', 4), ('body', 14)]], {}), 16: ('wagtail.blocks.CharBlock', (), {'default': 'Last updated', 'help_text': 'Label shown before the date (e.g. "All data last updated").', 'required': False}), 17: ('wagtail.blocks.CharBlock', (), {'help_text': 'Optional text after the date (e.g. "(no longer updating)").', 'required': False}), 18: ('wagtail.blocks.StructBlock', [[('label', 16), ('suffix', 17)]], {}), 19: ('wagtail.blocks.CharBlock', (), {'help_text': 'Key matching a figure in the DashboardData JSON.', 'required': True}), 20: ('wagtail.blocks.CharBlock', (), {'help_text': 'Accessibility description (aria-label) for the chart.', 'required': True}), 21: ('wagtail.blocks.IntegerBlock', (), {'default': 500, 'help_text': 'Chart height in pixels.', 'required': True}), 22: ('wagtail.blocks.CharBlock', (), {'help_text': 'Optional visible caption below the chart (separate from alt text).', 'required': False}), 23: ('wagtail.blocks.URLBlock', (), {'help_text': 'Link to the viz script in this repo on GitHub.', 'required': False}), 24: ('wagtail.blocks.BooleanBlock', (), {'default': False, 'help_text': 'Show a link to download the underlying data file.', 'required': False}), 25: ('wagtail.blocks.StructBlock', [[('figure_id', 19), ('alt_text', 20), ('height', 21), ('caption', 22), ('script_github_url', 23), ('show_data_download', 24)]], {}), 26: ('wagtail.images.blocks.ImageChooserBlock', (), {'help_text': 'Upload an image, or leave empty and provide an external URL below.', 'required': False}), 27: ('wagtail.blocks.URLBlock', (), {'help_text': 'External image URL (e.g., Github, blobserver SVG). Used when no image is uploaded.', 'required': False}), 28: ('wagtail.blocks.CharBlock', (), {'help_text': 'Accessibility description (alt attribute) for the image.', 'required': True}), 29: ('wagtail.blocks.CharBlock', (), {'help_text': 'Optional visible caption below the figure (separate from alt text).', 'required': False}), 30: ('wagtail.blocks.StructBlock', [[('image', 26), ('image_url', 27), ('alt_text', 28), ('caption', 29)]], {}), 31: ('wagtail.blocks.StructBlock', [[]], {})}, default=list),
        ),
        migrations.RunPython(copy_parent_content_to_liver_content, noop_reverse),
        migrations.RunPython(insert_hepagene_panel, noop_reverse),
    ]
