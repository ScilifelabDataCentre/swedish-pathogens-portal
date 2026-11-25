"""HepaGeNIE interactive panel StreamField block (sidebar + TLN)."""

from wagtail.blocks import StaticBlock


class HepageniePanelBlock(StaticBlock):
    """StreamField slot for the live HepaGeNIE sidebar and TLN.

    Editors place this block once in StreamField order so content above/below
    it sits above/below the interactive dashboard. It is not a static Plotly
    figure — use Plotly figure for pre-computed charts.

    The block template includes the shared interactive grid partial (sidebar,
    TLN, legend). Page context (session, examples, figures) is supplied by the
    parent page.
    """

    class Meta:
        """Block metadata."""

        template = "cms/blocks/hepagene_panel.html"
        icon = "view"
        label = "HepaGeNIE interactive panel"
        admin_text = (
            "Place exactly once; renders the interactive HepaGeNIE sidebar + TLN. "
            "Drag StreamField blocks above or below it for layout."
        )
