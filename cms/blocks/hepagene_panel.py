"""HepaGeNIE interactive panel StreamField block (sidebar + TLN)."""

from wagtail import blocks


class HepageniePanelBlock(blocks.StructBlock):
    """StreamField slot for the live HepaGeNIE sidebar and TLN.

    Editors place this block in StreamField order so content above/below it
    sits above/below the interactive dashboard. It is not a static Plotly
    figure — use Plotly figure for pre-computed charts.

    The block template includes the shared interactive grid partial (sidebar,
    TLN, legend). Page context (session, examples, figures) is supplied by the
    parent page; until cut-over the page still renders that grid itself.
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
