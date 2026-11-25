"""Unit tests for ``HepageniePanelBlock`` metadata and template."""

from pathlib import Path

from django.test import SimpleTestCase
from wagtail.blocks import StaticBlock

from cms.blocks import HepageniePanelBlock
from cms.blocks.hepagene_panel import HepageniePanelBlock as HepageniePanelBlockDirect

_CMS_ROOT = Path(__file__).resolve().parents[2]


class TestHepageniePanelBlock(SimpleTestCase):
    """Smoke tests for the HepaGeNIE panel StreamField block."""

    def test_export_matches_direct_import(self) -> None:
        """cms.blocks export exposes the same class as the module."""
        self.assertIs(HepageniePanelBlock, HepageniePanelBlockDirect)

    def test_is_static_block_with_admin_text(self) -> None:
        """Panel is a StaticBlock with editor admin_text (contact/ENA pattern)."""
        block = HepageniePanelBlock()
        self.assertIsInstance(block, StaticBlock)
        self.assertEqual(block.meta.label, "HepaGeNIE interactive panel")
        self.assertEqual(block.meta.template, "cms/blocks/hepagene_panel.html")
        self.assertIn("exactly once", block.meta.admin_text)

    def test_block_template_includes_interactive_grid_partial(self) -> None:
        """Block template delegates to the shared sidebar+TLN partial."""
        source = (_CMS_ROOT / "templates/cms/blocks/hepagene_panel.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "cms/pages/liver_resource/partials/interactive_grid.html",
            source,
        )
        grid = (
            _CMS_ROOT / "templates/cms/pages/liver_resource/partials/interactive_grid.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="tln-container"', grid)
        self.assertIn('id="liver-colour-legend"', grid)
        self.assertNotIn("until cut-over", grid)
