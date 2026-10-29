"""ENA data block: the Genomic data page's searchable listing of Swedish pathogen records."""

from wagtail.blocks import StaticBlock


class EnaDataBlock(StaticBlock):
    """Shows Swedish pathogen records from ENA, with facets, search and sorting.

    The records come from EBI Search (the same source as the central Pathogens
    Portal), so there is nothing to configure here.
    """

    class Meta:
        """Block metadata."""

        icon = "table"
        label = "ENA data"
        template = "cms/blocks/ena_data.html"
        admin_text = (
            "Shows Swedish pathogen records from ENA (via EBI Search), with facets, search and "
            "sorting. NOTE: The records are loaded via HTMX and require the page to be "
            "published. Until this page is published, previewing it will show an error."
        )
