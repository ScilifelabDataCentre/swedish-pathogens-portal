"""Test the Editors Approval Task."""

from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from wagtail.models import AbstractGroupApprovalTask

from cms.workflows.editors_approval import EditorsApprovalTask


class TestEditorsApprovalTask(TestCase):
    """Test the Editors Approval Task."""

    def setUp(self):
        """Set up the test case."""
        self.user = MagicMock(id=1)
        self.other_user = MagicMock(id=2)
        self.task = EditorsApprovalTask()

    def test_excludes_own_tasks_when_self_approval_disabled(self):
        """Test that own tasks are excluded when self-approval is disabled."""
        qs = MagicMock()

        with (
            patch.object(
                AbstractGroupApprovalTask, "get_task_states_user_can_moderate", return_value=qs
            ),
            patch("cms.workflows.editors_approval.self_approval_disabled", return_value=True),
        ):
            self.task.get_task_states_user_can_moderate(self.user)

        qs.exclude.assert_called_once_with(workflow_state__requested_by=self.user)

    def test_does_not_exclude_own_tasks_when_self_approval_enabled(self):
        """Test that own tasks are not excluded when self-approval is enabled."""
        qs = MagicMock()

        with (
            patch.object(
                AbstractGroupApprovalTask, "get_task_states_user_can_moderate", return_value=qs
            ),
            patch("cms.workflows.editors_approval.self_approval_disabled", return_value=False),
        ):
            result = self.task.get_task_states_user_can_moderate(self.user)

        qs.exclude.assert_not_called()
        self.assertIs(result, qs)

    def test_on_action_raises_for_self_approval_when_disabled(self):
        """Test that self-approval raises PermissionDenied when disabled."""
        task_state = MagicMock()
        task_state.workflow_state.requested_by_id = self.user.id

        with (
            patch("cms.workflows.editors_approval.self_approval_disabled", return_value=True),
            self.assertRaises(PermissionDenied),
        ):
            self.task.on_action(task_state, self.user, "approve")

    def test_on_action_allows_self_approval_when_enabled(self):
        """Test that self-approval is allowed when enabled."""
        task_state = MagicMock()
        task_state.workflow_state.requested_by_id = self.user.id

        with (
            patch("cms.workflows.editors_approval.self_approval_disabled", return_value=False),
            patch.object(AbstractGroupApprovalTask, "on_action") as parent_on_action,
        ):
            self.task.on_action(task_state, self.user, "approve")

        parent_on_action.assert_called_once_with(task_state, self.user, "approve")

    def test_on_action_allows_other_user_when_self_approval_disabled(self):
        """Test that other users can approve when self-approval is disabled."""
        task_state = MagicMock()
        task_state.workflow_state.requested_by_id = self.other_user.id

        with (
            patch("cms.workflows.editors_approval.self_approval_disabled", return_value=True),
            patch.object(AbstractGroupApprovalTask, "on_action") as parent_on_action,
        ):
            self.task.on_action(task_state, self.user, "approve")

        parent_on_action.assert_called_once_with(task_state, self.user, "approve")
