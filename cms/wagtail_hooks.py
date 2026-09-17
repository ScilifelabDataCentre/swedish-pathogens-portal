"""Wagtail hooks for the CMS."""

from wagtail import hooks
from wagtail.rich_text import FeatureRegistry

from .handlers.external_link import ExternalLinkNewTabHandler
from .snippets.dashboard_data import DashboardDataDeleteBulkAction

# Override Wagtail's generic deletion handler for this snippet only, after its
# default registration (order 0), including direct requests to the bulk URL.
hooks.register("register_bulk_action", DashboardDataDeleteBulkAction, order=1)


@hooks.register("register_rich_text_features")
def register_external_link(features: FeatureRegistry) -> None:
    """Register the external link handler as a rich text feature."""
    features.register_link_type(ExternalLinkNewTabHandler)
