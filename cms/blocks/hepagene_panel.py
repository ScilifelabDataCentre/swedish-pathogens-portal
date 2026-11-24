"""HepaGeNIE interactive panel StreamField block (sidebar + TLN)."""

from wagtail import blocks


class HepageniePanelBlock(blocks.StructBlock):
    """Placeholder slot for the live HepaGeNIE sidebar and TLN.

    Editors place this block in StreamField order so content above/below it
    sits above/below the interactive dashboard. It is not a static Plotly
    figure — use Plotly figure for pre-computed charts.

    No editor fields yet; later commits render the interactive UI from the
    block template using page context.
    """

    class Meta:
        """Block metadata."""

        template = "cms/blocks/hepagene_panel.html"
        icon = "view"
        label = "HepaGeNIE interactive panel"
        help_text = (
            "Interactive HepaGeNIE sidebar + TLN (not a static Plotly figure). "
            "Place once; drag StreamField blocks above or below it for layout."
        )
