"""Workflow moderation panel for the Wagtail admin landing page."""

from typing import TYPE_CHECKING, Any

from wagtail.admin.views.home import UserObjectsInWorkflowModerationPanel

if TYPE_CHECKING:
    from wagtail.admin.ui.components import Component


class CustomUserObjectsInWorkflowModerationPanel(UserObjectsInWorkflowModerationPanel):
    """Custom workflow moderation panel for the Wagtail admin home page.

    This panel is a subclass of the default Wagtail workflow moderation panel, which
    displays a list of pages that are currently in the workflow moderation process for
    the logged-in user. The custom panel overrides the default behaviour to only display
    pages that were submitted for approval by the logged-in user, rather than pages
    created by the user. This panel is registered with the Wagtail admin home page
    using the `construct_homepage_panels` hook.

    NOTE: This works as intended for now, but it feels a bit patchy, since the default
    panel is not registered as a hook. We need to keep an eye on the tests, and if this
    breaks often in the future with new Wagtail releases, we might have to change it.
    """

    def get_context_data(self, parent_context: dict[str, Any]) -> dict[str, Any]:
        """Get the context data for the workflow moderation panel."""
        context = super().get_context_data(parent_context)
        user = getattr(context.get("request"), "user", None)

        if user is not None:
            context["workflow_states"] = [
                state for state in context["workflow_states"] if state.requested_by_id == user.id
            ]

        return context


# Helper function to be used in the wagtail_hooks.py file to replace the
# default workflow moderation panel with the custom one defined above.
# As mentioned in the class docstring, this is a bit patchy, this will
# be changed together with the class if this breaks often in future with
# new Wagtail releases. For now, this works as intended.
def replace_user_objects_in_workflow_moderation_panel(panels: list[Component]) -> None:
    """Replace Wagtail's workflow moderation panel with our custom panel."""
    for index, panel in enumerate(panels):
        if isinstance(panel, UserObjectsInWorkflowModerationPanel):
            panels[index] = CustomUserObjectsInWorkflowModerationPanel()
