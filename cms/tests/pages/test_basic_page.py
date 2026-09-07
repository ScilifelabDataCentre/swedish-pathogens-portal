"""Tests for the generic ``BasicPage`` content type.

Covers the three contracts the 2320 rework introduced: unrestricted
placement (no ``parent_page_types``/``subpage_types``), the available
``content`` block types (including the new ``collapsible``), and a
full-page render of a published page carrying rich text, a collapsible
section, and a top-level data table.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import BasicPage, HomePage

_INTRO_TEXT = "Generic basic page intro copy."
_TABLE_ID = "metrics"


def _content_with_blocks(
    intro: str = _INTRO_TEXT, table_id: str = _TABLE_ID, include_matomo_opt_out: bool = False
) -> str:
    """Return StreamField JSON content for a basic page.

    Contains a rich-text intro, a collapsible, a data table and an optional matomo_opt_out block.

    Mirrors the JSON Wagtail serialises for ``BasicPage.content``: a top-level
    ``text`` block, a ``collapsible`` whose body holds one inner rich-text block
    (``CollapsibleBlock.body`` enforces ``min_num=1``), and a top-level
    ``data_table`` that renders the ``id="data-table-<id>-title"`` caption marker.
    """
    blocks = [
        {"type": "text", "value": f"<p>{intro}</p>", "id": "block-intro"},
        {
            "type": "collapsible",
            "value": {
                "label": "Programme timeline",
                "body": [
                    {
                        "type": "text",
                        "value": "<p>Inner disclosure copy</p>",
                        "id": "inner-text",
                    },
                ],
            },
            "id": "block-collapsible",
        },
        {
            "type": "data_table",
            "value": {
                "table_id": table_id,
                "show_controls": True,
                "per_page": "10",
                "table": {
                    "columns": [
                        {"type": "text", "heading": "Name"},
                        {"type": "numeric", "heading": "Score"},
                    ],
                    "rows": [{"values": ["Alice", 95.0]}],
                    "caption": "Programme metrics",
                },
            },
            "id": "block-table",
        },
    ]
    if include_matomo_opt_out:
        blocks.append({"type": "matomo_opt_out", "value": {}, "id": "block-matomo-opt-out"})
    return json.dumps(blocks)


class BasicPagePlacementTest(WagtailPageTestCase):
    """``BasicPage`` is a generic page: no placement restrictions."""

    def test_placement_attributes_are_absent(self) -> None:
        """Neither ``parent_page_types`` nor ``subpage_types`` is set on the class."""
        self.assertNotIn("parent_page_types", vars(BasicPage))
        self.assertNotIn("subpage_types", vars(BasicPage))

    def test_basic_page_allowed_under_home_page(self) -> None:
        """A ``BasicPage`` may be created beneath a ``HomePage``."""
        self.assertIn(BasicPage, HomePage.allowed_subpage_models())

    def test_basic_page_allowed_under_basic_page(self) -> None:
        """A ``BasicPage`` may be nested beneath another ``BasicPage``."""
        self.assertIn(BasicPage, BasicPage.allowed_subpage_models())

    def test_home_page_is_an_allowed_parent(self) -> None:
        """``HomePage`` is a permitted parent of ``BasicPage``."""
        self.assertIn(HomePage, BasicPage.allowed_parent_page_models())

    def test_basic_page_cannot_be_created_under_root(self) -> None:
        """A ``BasicPage`` may not be created directly beneath the Wagtail root."""
        root = Page.get_first_root_node()

        self.assertFalse(BasicPage.can_create_at(root))

    def test_basic_page_cannot_be_moved_under_root(self) -> None:
        """An existing ``BasicPage`` may not be moved directly beneath the Wagtail root."""
        root = Page.get_first_root_node()
        basic_page = BasicPage()

        self.assertFalse(basic_page.can_move_to(root))


class BasicPageContentBlocksTest(SimpleTestCase):
    """``BasicPage.content`` exposes exactly the expected block types."""

    def test_content_block_set_is_trimmed(self) -> None:
        """Only expected blocks are allowed."""
        child_blocks = BasicPage._meta.get_field("content").stream_block.child_blocks
        self.assertEqual(
            set(child_blocks.keys()),
            {"text", "alert", "data_table", "collapsible", "matomo_opt_out"},
        )


class BasicPageRenderTest(WagtailPageTestCase):
    """Full-page render of published ``BasicPage`` instances."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish three BasicPages for tests.

        one with mixed content, one empty, and one "privacy" page containing a matomo_opt_out block.
        """
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": cls.home},
        )

        cls.page = BasicPage(title="Basic Page", slug="basic-page")
        cls.page.content = _content_with_blocks()
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

        cls.empty_page = BasicPage(title="Empty Page", slug="empty-page")
        cls.home.add_child(instance=cls.empty_page)
        cls.empty_page.save_revision().publish()

        cls.privacy_page = BasicPage(title="Privacy Policy", slug="privacy")
        cls.privacy_page.content = _content_with_blocks(include_matomo_opt_out=True)
        cls.home.add_child(instance=cls.privacy_page)
        cls.privacy_page.save_revision().publish()

    def test_renders_intro_collapsible_and_data_table(self) -> None:
        """The page returns 200 with the intro, a ``<details``, and the table marker."""
        resp = self.client.get(self.page.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, _INTRO_TEXT)
        self.assertContains(resp, "<details")
        self.assertContains(resp, f'id="data-table-{_TABLE_ID}-title"')

    def test_empty_content_page_renders(self) -> None:
        """A ``BasicPage`` with empty ``content`` still publishes and renders 200."""
        resp = self.client.get(self.empty_page.url)
        self.assertEqual(resp.status_code, 200)

    def test_matomo_opt_out_block_renders_in_privacy_page(self) -> None:
        """The ``matomo_opt_out`` block renders the expected widget from the script."""
        resp = self.client.get(self.privacy_page.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="matomo-opt-out"')
        self.assertContains(
            resp, "https://matomo.dc.scilifelab.se/index.php?module=CoreAdminHome&action=optOutJS"
        )
