"""Unit tests for ``CollapsibleBlock`` validation and rendering."""

from __future__ import annotations

from typing import Any

from django.test import SimpleTestCase
from wagtail.blocks import StructBlockValidationError

from cms.blocks.collapsible import CollapsibleBlock


def _data_table_value(table_id: str = "timeline") -> dict[str, Any]:
    """Return a minimal ``DataTableBlock`` value dict that survives ``to_python``.

    The shape mirrors the JSON Wagtail emits when a ``TypedTableBlock``
    is serialised inside a StreamField, with a non-empty caption (required
    by ``DataTableBlock.clean``) and a single text row.
    """
    return {
        "table_id": table_id,
        "show_controls": False,
        "per_page": "10",
        "table": {
            "columns": [
                {"type": "text", "heading": "Date"},
                {"type": "text", "heading": "Milestone"},
            ],
            "rows": [{"values": ["2025-06-01", "PLPTDP25 Call"]}],
            "caption": "Timeline of the PLP program",
        },
    }


class TestCollapsibleBlock(SimpleTestCase):
    """Tests for the CollapsibleBlock structural and rendering contract."""

    def setUp(self) -> None:
        """Create a fresh block under test."""
        self.block = CollapsibleBlock()

    def test_renders_details_summary_with_label_and_text_body(self) -> None:
        """Rendered HTML wraps the label and a text body inside <details>/<summary>."""
        value = self.block.to_python(
            {
                "label": "Timeline of the program",
                "body": [
                    {"type": "text", "value": "<p>Inner timeline copy</p>"},
                ],
            }
        )

        html = self.block.render(value)

        self.assertIn("<details", html)
        self.assertIn("<summary", html)
        self.assertIn("Timeline of the program", html)
        self.assertIn("Inner timeline copy", html)

    def test_renders_inner_data_table_marker(self) -> None:
        """An inner DataTableBlock contributes its unique id marker to the output."""
        value = self.block.to_python(
            {
                "label": "Timeline of the program",
                "body": [
                    {"type": "data_table", "value": _data_table_value("timeline")},
                ],
            }
        )

        html = self.block.render(value)

        self.assertIn("<details", html)
        self.assertIn("<summary", html)
        self.assertIn("Timeline of the program", html)
        self.assertIn("data-table-timeline", html)

    def test_data_table_caption_inside_collapsible_is_screen_reader_only(self) -> None:
        """Nested data_table caption keeps its id (aria) but is visually hidden via wrapper.

        The collapsible ``<summary>`` already shows the section label; the inner
        ``DataTableBlock`` caption would duplicate it as a visible ``<h3>`` without
        a scoped ``sr-only`` rule on the collapsible body wrapper.
        """
        value = self.block.to_python(
            {
                "label": "Timeline of the program",
                "body": [
                    {"type": "data_table", "value": _data_table_value("timeline")},
                ],
            }
        )

        html = self.block.render(value)
        sr_only_variant = "[&_[id^='data-table-'][id$='-title']]:sr-only"
        caption_id = 'id="data-table-timeline-title"'

        self.assertIn(sr_only_variant, html)
        self.assertIn(caption_id, html)
        self.assertGreater(html.find(caption_id), html.find(sr_only_variant))

    def test_label_is_required(self) -> None:
        """An empty label raises StructBlockValidationError on the label field."""
        value = self.block.to_python(
            {
                "label": "",
                "body": [
                    {"type": "text", "value": "<p>Body</p>"},
                ],
            }
        )

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        self.assertIn("label", ctx.exception.block_errors)

    def test_body_min_num_enforced(self) -> None:
        """An empty body raises StructBlockValidationError on the body field."""
        value = self.block.to_python(
            {
                "label": "Timeline",
                "body": [],
            }
        )

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        self.assertIn("body", ctx.exception.block_errors)

    def test_clean_forces_show_controls_false_on_nested_data_table(self) -> None:
        """``show_controls=True`` on a nested ``data_table`` is coerced to ``False``.

        HTMX search/pagination URLs target ``cms:table_partial``, whose lookup
        only scans top-level page blocks — a nested controlled table would 404.
        """
        table_value = _data_table_value("timeline")
        table_value["show_controls"] = True
        value = self.block.to_python(
            {
                "label": "Timeline",
                "body": [
                    {"type": "data_table", "value": table_value},
                ],
            }
        )

        cleaned = self.block.clean(value)

        child = cleaned["body"][0]
        self.assertEqual(child.block_type, "data_table")
        self.assertFalse(child.value["show_controls"])

    def test_rendered_nested_data_table_omits_htmx_controls(self) -> None:
        """Rendered HTML for a nested ``data_table`` never emits ``hx-get`` URLs.

        ``CollapsibleBlock.clean`` flips ``show_controls`` to ``False``, so the
        data-table component template skips both the search/per-page bar and
        the pagination buttons — keeping the 404-prone partial URL out of the DOM.
        """
        table_value = _data_table_value("timeline")
        table_value["show_controls"] = True
        value = self.block.to_python(
            {
                "label": "Timeline",
                "body": [
                    {"type": "data_table", "value": table_value},
                ],
            }
        )

        html = self.block.render(self.block.clean(value))

        self.assertNotIn("hx-get", html)
        self.assertNotIn("data-table-timeline-controls", html)
