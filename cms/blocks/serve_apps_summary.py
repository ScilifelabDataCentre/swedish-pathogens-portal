"""Serve apps summary block: app counts linking into the Models and apps page."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from wagtail.blocks import CharBlock, ChoiceBlock, IntegerBlock, PageChooserBlock, StructBlock

BREAKDOWN_CHOICES = [
    ("keyword", "Pathogen keyword"),
    ("type", "App type"),
]


class ServeAppsSummaryBlock(StructBlock):
    """Shows the number of apps on a Models and apps page, broken down by pathogen or type.

    Like the Portal data summary block, but loaded via HTMX from the Models and apps page
    itself: fetching Serve's catalogue can take a while when it isn't cached, and the page
    shouldn't wait for it. The counts follow the page's own "Always show" and "Never show"
    settings. Renders nothing if the chosen page isn't live.

    Attributes:
        page: The Models and apps page whose apps are summarised and linked to.
        title: Optional section heading, defaults to the page's title.
        breakdown: The facet used for the per-value buttons.
        max_rows: Maximum number of breakdown buttons to show.
    """

    page = PageChooserBlock(
        page_type="cms.ServeAppsPage",
        help_text="The Models and apps page to summarise and link to.",
    )
    title = CharBlock(
        required=False,
        help_text='Section heading. Defaults to the page title (e.g. "Models and apps").',
    )
    breakdown = ChoiceBlock(
        choices=BREAKDOWN_CHOICES,
        default="keyword",
        help_text="Which field to break the app counts down by.",
    )
    max_rows = IntegerBlock(
        default=8,
        min_value=1,
        max_value=50,
        help_text="Maximum number of breakdown buttons to show.",
    )

    class Meta:
        """Block metadata."""

        template = "cms/blocks/serve_apps_summary.html"
        icon = "table"
        label = "Serve apps summary"
        help_text = (
            "Shows app counts from a Models and apps page, with links to the filtered listing. "
            "NOTE: The counts are loaded via HTMX and require both pages to be published."
        )

    def get_context(self, value: Any, parent_context: dict | None = None) -> dict[str, Any]:  # noqa: ANN401
        """Add the URL the summary section is loaded from (``summary_url``) to the context."""
        context = super().get_context(value, parent_context=parent_context)
        context["summary_url"] = None

        page = value.get("page")
        if page is None or not page.live:
            return context

        listing_url = page.get_url(request=(parent_context or {}).get("request"))
        if not listing_url:
            return context

        params = {
            "summary": value.get("breakdown") or "keyword",
            "rows": value.get("max_rows") or 8,
        }
        if value.get("title"):
            params["title"] = value["title"]
        context["summary_url"] = f"{listing_url}?{urlencode(params)}"
        return context
