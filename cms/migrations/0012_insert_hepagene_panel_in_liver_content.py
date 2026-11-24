"""Insert HepageniePanel into existing liver_content streams (layout cut-over)."""

from __future__ import annotations

import uuid
from typing import Any

from django.db import migrations

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


def noop_reverse(apps, schema_editor):
    """Keep panels on reverse; removing them would drop editor layout."""


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0011_add_liver_content_hepagene_panel"),
    ]

    operations = [
        migrations.RunPython(insert_hepagene_panel, noop_reverse),
    ]
