"""Serve apps block: the Models and apps page's searchable listing of apps on SciLifeLab Serve."""

from wagtail.blocks import IntegerBlock, ListBlock, StructBlock


class ServeAppsBlock(StructBlock):
    """Shows the pathogen-related public apps and models on SciLifeLab Serve.

    Apps are picked automatically, by matching pathogen keywords in their name and
    description. Editors can add apps the keywords miss, or hide false positives,
    by their Serve ID (shown on each app's card).
    """

    # Both lists are optional: they start empty, and blank entries are ignored.
    include_app_ids = ListBlock(
        IntegerBlock(min_value=1, required=False),
        default=[],
        label="Always show",
        help_text=(
            "Optional. Serve IDs of apps to show even though no pathogen keyword matched them. "
            "Find an app's ID in the public-apps list: "
            "https://serve.scilifelab.se/openapi/v1/public-apps"
        ),
    )
    exclude_app_ids = ListBlock(
        IntegerBlock(min_value=1, required=False),
        default=[],
        label="Never show",
        help_text=(
            "Optional. Serve IDs of apps to hide even though a pathogen keyword matched them. "
            "The ID is shown at the bottom of each app's card on this page."
        ),
    )

    class Meta:
        """Block metadata."""

        icon = "table"
        label = "Serve apps"
        template = "cms/blocks/serve_apps.html"
        help_text = (
            "Shows the pathogen-related public apps and models on SciLifeLab Serve, with "
            "search, filters and sorting. NOTE: The apps are loaded via HTMX and require the "
            "page to be published. Until this page is published, previewing it will show an error."
        )
