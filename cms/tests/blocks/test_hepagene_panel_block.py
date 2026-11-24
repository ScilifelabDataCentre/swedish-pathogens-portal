"""Unit tests for ``HepageniePanelBlock`` metadata."""

from django.test import SimpleTestCase

from cms.blocks import HepageniePanelBlock
from cms.blocks.hepagene_panel import HepageniePanelBlock as HepageniePanelBlockDirect


class TestHepageniePanelBlock(SimpleTestCase):
    """Smoke tests for the HepaGeNIE panel StreamField stub."""

    def test_export_matches_direct_import(self) -> None:
        """cms.blocks export exposes the same class as the module."""
        self.assertIs(HepageniePanelBlock, HepageniePanelBlockDirect)

    def test_meta_label_and_template(self) -> None:
        """Editor label and stub template are set for later StreamField wiring."""
        block = HepageniePanelBlock()
        self.assertEqual(block.meta.label, "HepaGeNIE interactive panel")
        self.assertEqual(block.meta.template, "cms/blocks/hepagene_panel.html")
        self.assertFalse(block.child_blocks)
