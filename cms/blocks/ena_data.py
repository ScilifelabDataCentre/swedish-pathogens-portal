"""ENA data block for listing Swedish pathogen records from the European Nucleotide Archive."""

from wagtail.blocks import CharBlock, IntegerBlock, ListBlock, StructBlock


class EnaPathogenBlock(StructBlock):
    """A pathogen whose Swedish records are listed from ENA."""

    name = CharBlock(max_length=255, help_text="Pathogen name shown in the sidebar.")
    taxon_ids = ListBlock(
        IntegerBlock(min_value=1),
        min_num=1,
        help_text=(
            "One or more NCBI taxonomy ids, e.g. 2697049 for SARS-CoV-2. Records from this "
            "taxon and everything below it (strains, lineages, etc.) are included. Use multiple "
            "ids if the pathogen spans several taxa. Ids can be looked up at "
            "https://www.ebi.ac.uk/ena/browser/ or https://www.ncbi.nlm.nih.gov/taxonomy."
        ),
    )

    class Meta:
        """Block metadata."""

        icon = "site"


class EnaDataBlock(StructBlock):
    """A block listing Swedish records from ENA, filtered by pathogen and record type."""

    pathogens = ListBlock(
        EnaPathogenBlock(),
        min_num=1,
        help_text="One entry per pathogen to filter on. Displayed alphabetically by name.",
    )

    class Meta:
        """Block metadata."""

        icon = "table"
        label = "ENA data"
        template = "cms/blocks/ena_data.html"
        help_text = (
            "NOTE: The ENA records are loaded via HTMX and require the page to be published. "
            "Until this page is published, previewing it will show an error."
        )
