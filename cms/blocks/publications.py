"""Publications block for displaying a list of publications filtered by category."""

from wagtail.blocks import CharBlock, ListBlock, StructBlock


class PathogenBlock(StructBlock):
    """A block representing a single pathogen for filtering publications."""

    name = CharBlock(max_length=255, help_text="Pathogen name shown in the filter sidebar.")
    search_terms = ListBlock(
        CharBlock(max_length=50),
        min_num=1,
        help_text=(
            "One or more search terms to match against the publication's title or abstract. "
            "The query will be constructed as an 'OR' search across all terms. "
            "Use multiple terms if the pathogen has multiple names or abbreviations."
        ),
    )

    class Meta:
        """Block metadata."""

        icon = "site"


class PublicationsBlock(StructBlock):
    """A block for displaying a list of publications filtered by pathogen."""

    pathogens = ListBlock(
        PathogenBlock(),
        min_num=1,
        help_text="One entry per pathogen to for the filter. Order here is the display order.",
    )

    class Meta:
        """Block metadata."""

        icon = "list-ul"
        template = "cms/pages/publications/partials/publications_section.html"
