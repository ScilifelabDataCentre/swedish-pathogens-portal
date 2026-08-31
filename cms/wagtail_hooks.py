"""Wagtail hooks for the CMS."""

from typing import TYPE_CHECKING, Any

from django.shortcuts import redirect
from wagtail import hooks
from wagtail.admin import messages

from cms.forms.workflow_panel import replace_user_objects_in_workflow_moderation_panel
from cms.handlers.external_link import ExternalLinkNewTabHandler
from cms.services.spp_settings import direct_publishing_disabled, self_approval_disabled

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from wagtail.admin.ui.components import Component
    from wagtail.admin.ui.menus import MenuItem
    from wagtail.admin.views.bulk_action import BulkAction
    from wagtail.models import Page
    from wagtail.rich_text import FeatureRegistry


# -----------------------------------------------------------------------------
# Register rich text features for external links
# -----------------------------------------------------------------------------


@hooks.register("register_rich_text_features")
def register_external_link(features: FeatureRegistry) -> None:
    """Register the external link handler as a rich text feature."""
    features.register_link_type(ExternalLinkNewTabHandler)


# -----------------------------------------------------------------------------
# Register hooks for publishing and workflow actions
# -----------------------------------------------------------------------------

publish_error_message = (
    "Direct publishing of pages is disabled. Please submit the page for approval."
)


@hooks.register("before_publish_page")
def prevent_direct_publish(
    request: HttpRequest, page: Page, **kwargs: dict[str, Any]
) -> None | HttpResponse:
    """Prevent direct publishing of pages."""
    # this hook is not called by approved workflow action, so this is added
    # as an extra layer of security to prevent direct publishing of pages.
    if direct_publishing_disabled():
        messages.error(request, publish_error_message)
        return redirect("wagtailadmin_home")


@hooks.register("before_bulk_action")
def prevent_bulk_direct_publish(
    request: HttpRequest, action_type: str, objects: list[Page], action_class_instance: BulkAction
) -> None | HttpResponse:
    """Prevent direct publishing of pages via bulk action."""

    # this hook is not called by approved workflow action, so this is added as an
    # extra layer of security to prevent direct publishing of pages via bulk action.
    if direct_publishing_disabled() and action_type == "publish":
        messages.error(request, publish_error_message)
        return redirect("wagtailadmin_home")


@hooks.register("construct_page_action_menu")
def remove_not_allowed_actions(
    menu_items: list[MenuItem], request: HttpRequest, context: dict[str, Any]
) -> None:
    """Remove not allowed actions from the page action menu."""

    # Remove the "Publish" action from the page irrespective of the user and workflow
    # state, since the workflow system is used to control the publishing of pages.
    if direct_publishing_disabled():
        menu_items[:] = [item for item in menu_items if item.name != "action-publish"]

    user = getattr(request, "user", None)
    page_workflow_state = getattr(context.get("page"), "current_workflow_state", None)

    # Remove the "Approve" and "Reject" actions from the page action menu if
    # the page is in the approval workflow and the user is the same as the
    # one who requested the workflow i.e. submitted the page for approval.
    if (
        self_approval_disabled()
        and user
        and page_workflow_state
        and page_workflow_state.requested_by_id == user.id
    ):
        menu_items[:] = [item for item in menu_items if item.name not in ["approve", "reject"]]


# -----------------------------------------------------------------------------
# Hook to customize the homepage panels
# -----------------------------------------------------------------------------


@hooks.register("construct_homepage_panels")
def customise_homepage_panels(request: HttpRequest, panels: list[Component]) -> None:
    """Customize the homepage panels."""
    replace_user_objects_in_workflow_moderation_panel(panels)
