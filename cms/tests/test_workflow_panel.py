"""Test the Workflow Panel."""

from typing import Any
from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from wagtail.admin.views.home import UserObjectsInWorkflowModerationPanel
from wagtail.models import Page, Site, Workflow, WorkflowState, WorkflowTask

from cms.forms.workflow_panel import (
    CustomUserObjectsInWorkflowModerationPanel,
    replace_user_objects_in_workflow_moderation_panel,
)
from cms.pages.home import HomePage
from cms.workflows.editors_approval import EditorsApprovalTask


class TestCustomUserObjectsInWorkflowModerationPanel(TestCase):
    """Test the custom workflow moderation panel."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Set up the test case."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)

        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )
        cls.user = User.objects.create_superuser(
            username="editor",
            email="editor@example.com",
            password="password",  # noqa: S106
        )
        cls.other_user = User.objects.create_superuser(
            username="other-editor",
            email="other-editor@example.com",
            password="password",  # noqa: S106
        )

        cls.page = cls.home.add_child(
            instance=Page(title="Test page", slug="test-page", owner=cls.user)
        )
        cls.page.save_revision().publish()

        cls.other_page = cls.home.add_child(
            instance=Page(title="Other page", slug="other-page", owner=cls.other_user)
        )
        cls.other_page.save_revision().publish()

        cls.task = EditorsApprovalTask.objects.create(name="Editors Approval")
        cls.workflow = Workflow.objects.create(name="Test workflow")
        WorkflowTask.objects.create(workflow=cls.workflow, task=cls.task)

        cls.request_factory = RequestFactory()

    def _get_parent_context(self, user: User) -> dict[str, Any]:
        """Get the context for the custom workflow moderation panel."""
        request = self.request_factory.get("/")
        request.user = user

        return {"request": request}

    def test_wagtail_panel_expected_behaviour(self):
        """Test that Wagtail's panel shows the expected behaviour."""
        self.workflow.start(self.page, self.other_user)
        self.workflow.start(self.other_page, self.user)

        panel = UserObjectsInWorkflowModerationPanel()

        context = panel.get_context_data(self._get_parent_context(self.user))
        workflow_states = context["workflow_states"]

        # assert for expected objects
        self.assertIn("workflow_states", context)
        self.assertEqual(len(workflow_states), 2)
        self.assertIsInstance(workflow_states[0], WorkflowState)

    def test_custom_panel_filters_wagtail_workflow_states(self):
        """Test that the custom panel filters Wagtail workflow states by requester."""
        ws1 = self.workflow.start(self.page, self.other_user)

        panel = CustomUserObjectsInWorkflowModerationPanel()

        context = panel.get_context_data(self._get_parent_context(self.user))
        workflow_states = context["workflow_states"]

        self.assertNotIn(ws1, workflow_states)
        self.assertEqual(len(workflow_states), 0)

    def test_custom_panel_lists_only_user_workflow_states(self):
        """Test that the custom panel lists only workflow states started by the user."""
        ws1 = self.workflow.start(self.page, self.user)
        ws2 = self.workflow.start(self.other_page, self.other_user)

        panel = CustomUserObjectsInWorkflowModerationPanel()

        context = panel.get_context_data(self._get_parent_context(self.user))
        workflow_states = context["workflow_states"]

        self.assertIn(ws1, workflow_states)
        self.assertNotIn(ws2, workflow_states)


class TestReplaceUserObjectsInWorkflowModerationPanel(SimpleTestCase):
    """Test that the Wagtail workflow moderation panel is replaced."""

    def test_replaces_workflow_moderation_panel(self):
        """Test that the default Wagtail panel is replaced with the custom panel."""
        panels = [UserObjectsInWorkflowModerationPanel()]

        replace_user_objects_in_workflow_moderation_panel(panels)

        self.assertIsInstance(panels[0], CustomUserObjectsInWorkflowModerationPanel)

    def test_does_not_replace_other_panels(self):
        """Test that panels other than the workflow moderation panel are unchanged."""
        other_panel = MagicMock()
        panels = [other_panel]

        replace_user_objects_in_workflow_moderation_panel(panels)

        self.assertIs(panels[0], other_panel)

    def test_replaces_all_workflow_moderation_panels(self):
        """Test that every matching Wagtail panel is replaced."""
        panels = [
            UserObjectsInWorkflowModerationPanel(),
            MagicMock(),
            UserObjectsInWorkflowModerationPanel(),
        ]

        replace_user_objects_in_workflow_moderation_panel(panels)

        self.assertIsInstance(panels[0], CustomUserObjectsInWorkflowModerationPanel)
        self.assertIsInstance(panels[2], CustomUserObjectsInWorkflowModerationPanel)
        self.assertIsInstance(panels[1], MagicMock)
