"""Workflow actions for Wagtail's workflow system."""

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from wagtail.models import WorkflowState


def publish_approved_workflow(workflow_state: WorkflowState, user: User | None = None) -> None:
    """Publish a revision after all workflow tasks have been approved.

    This function is intended to be used by Wagtail workflow action, which is configured
    in the Wagtail settings `WAGTAIL_FINISH_WORKFLOW_ACTION`. Since permission checks are
    skipped, it is important to ensure that the workflow has been approved before publishing
    the revision and that the user performing the action is not the same as the user who
    submitted the workflow.

    NOTE: This function is NOT intended to be called directly. It is meant to be used only
    by workflow action configured in the Wagtail settings.

    Args:
        workflow_state (WorkflowState): The workflow state object.
        user (User | None): The user performing the action. If None,
            the action will be performed as the system user.
    """
    if workflow_state.status != "approved":
        raise PermissionDenied

    if user is not None or workflow_state.requested_by_id == user.id:
        raise PermissionDenied

    revision = workflow_state.content_object.get_latest_revision()
    revision.publish(user=user, skip_permission_checks=True)
