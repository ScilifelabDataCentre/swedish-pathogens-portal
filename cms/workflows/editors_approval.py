"""Custom approval workflow task for the CMS."""

from typing import TYPE_CHECKING, Any

from django.core.exceptions import PermissionDenied
from django.db import models
from wagtail.models import AbstractGroupApprovalTask

from cms.services.spp_settings import self_approval_disabled

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from wagtail.models import TaskState


class EditorsApprovalTask(AbstractGroupApprovalTask):
    """Custom approval task model to prevent self-approval.

    This class extends the AbstractGroupApprovalTask model to add additional checks
    for self-approval. It overrides the `on_action` methods to enforce the self-approval
    restrictions based on the settings defined in SppSettings. It also overrides the
    `get_task_states_user_can_moderate` method to filter out the user's own tasks in
    the dashboard panel displayed at admin homepage.
    """

    def get_task_states_user_can_moderate(
        self, user: User, **kwargs: dict[str, Any]
    ) -> models.QuerySet:
        """Get the task states that the user can moderate."""

        qs = super().get_task_states_user_can_moderate(user, **kwargs)
        if self_approval_disabled():
            qs = qs.exclude(workflow_state__requested_by=user)

        return qs

    def on_action(
        self, task_state: TaskState, user: User, action_name: str, **kwargs: dict[str, Any]
    ) -> None:
        """Override the on_action method to prevent self-approval."""

        if self_approval_disabled() and task_state.workflow_state.requested_by_id == user.id:
            raise PermissionDenied

        return super().on_action(task_state, user, action_name, **kwargs)

    class Meta:
        """Meta class for the EditorsApprovalTask model."""

        verbose_name = "Editors Approval Task"
        verbose_name_plural = "Editors Approval Tasks"
