"""Publications block for displaying a list of publications filtered by category."""

from django.core.exceptions import ValidationError
from wagtail.blocks import CharBlock, ListBlock, StructBlock


def validate_no_quotes(value: str) -> None:
    """Reject search terms containing a double quote, which would break the Europe PMC query."""
    if '"' in value:
        raise ValidationError('Quotes (") are not allowed in search terms.')


class PathogenBlock(StructBlock):
    """A block representing a single pathogen for filtering publications."""

    name = CharBlock(max_length=255, help_text="Pathogen name shown in the filter sidebar.")
    search_terms = ListBlock(
        CharBlock(max_length=50, validators=[validate_no_quotes]),
        min_num=1,
        help_text=(
            "One or more search terms to match against the publication's title or abstract. "
            "The query will be constructed as an 'OR' search across all terms. "
            "Use multiple terms if the pathogen has multiple names or abbreviations. "
            "Don't use quotes in the search terms."
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
        help_text="One entry per pathogen to filter on. Order here is the display order.",
    )

    class Meta:
        """Block metadata."""

        icon = "list-ul"
        template = "cms/pages/publications/partials/publications_section.html"
        help_text = (
            "NOTE: The publications list is loaded via HTMX and requires the page to be published. "
            "Until this page is published, previewing it will show an error."
        )
