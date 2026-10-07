"""Portal data summary block: study counts linking into the Portal data listing."""

from __future__ import annotations

from typing import Any

from wagtail.blocks import CharBlock, ChoiceBlock, IntegerBlock, PageChooserBlock, StructBlock

from portal_data.summary import build_portal_data_summary

BREAKDOWN_CHOICES = [
    ("technology", "Technology"),
    ("platforms", "Platforms"),
    ("year", "Year"),
    ("design_types", "Design types"),
    ("factors", "Factors"),
    ("repository", "Repository"),
]


class PortalDataSummaryBlock(StructBlock):
    """Shows the number of studies in a Portal data page, broken down by one facet.

    Rendered server-side (no HTMX) since the data is local and the counts are cached.
    Renders nothing if the chosen page isn't live.

    Attributes:
        page: The Portal data page whose studies are summarised and linked to.
        title: Optional section heading, defaults to the page's datatype label.
        breakdown: The facet used for the per-value buttons.
        max_rows: Maximum number of breakdown buttons to show.
        country: Optional country filter, blank to include all studies.
    """

    page = PageChooserBlock(
        page_type="cms.PortalDataPage",
        help_text="The Portal data page to summarise and link to.",
    )
    title = CharBlock(
        required=False,
        help_text='Section heading. Defaults to the data type (e.g. "Metabolomics").',
    )
    breakdown = ChoiceBlock(
        choices=BREAKDOWN_CHOICES,
        default="technology",
        help_text="Which field to break the study counts down by.",
    )
    max_rows = IntegerBlock(
        default=8,
        min_value=1,
        max_value=50,
        help_text="Maximum number of breakdown buttons to show.",
    )
    country = CharBlock(
        required=False,
        help_text=(
            'Only count studies from this country (e.g. "Sweden"). '
            "Leave blank to include all studies."
        ),
    )

    class Meta:
        """Block metadata."""

        template = "cms/blocks/portal_data_summary.html"
        icon = "table"
        label = "Portal data summary"
        help_text = (
            "Shows study counts from a Portal data page, with links to the filtered listing."
        )

    def get_context(self, value: Any, parent_context: dict | None = None) -> dict[str, Any]:  # noqa: ANN401
        """Add the summary ``section`` dict to the block's template context."""
        context = super().get_context(value, parent_context=parent_context)
        context["section"] = None

        page = value.get("page")
        if page is None or not page.live:
            return context

        page = page.specific
        request = (parent_context or {}).get("request")
        listing_url = page.get_url(request=request)
        if not listing_url:
            return context

        context["section"] = build_portal_data_summary(
            datatype=page.datatype.strip().lower(),
            listing_url=listing_url,
            facet=value.get("breakdown") or "technology",
            country=value.get("country") or "",
            title=value.get("title") or "",
            max_rows=value.get("max_rows") or 8,
        )
        return context
