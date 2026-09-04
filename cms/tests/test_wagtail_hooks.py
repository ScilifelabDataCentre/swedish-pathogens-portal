"""Tests for the Wagtail hooks."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib import messages
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from wagtail.models import Page
from wagtail.rich_text import features

from cms.handlers.external_link import ExternalLinkNewTabHandler
from cms.wagtail_hooks import (
    customise_homepage_panels,
    prevent_bulk_direct_publish,
    prevent_direct_publish,
    publish_error_message,
    remove_not_allowed_actions,
)

# -----------------------------------------------------------------------------
# Test external link feature registration
# -----------------------------------------------------------------------------


class TestExternalLinkFeature(SimpleTestCase):
    """Tests for the external link feature registration."""

    def test_register_external_link(self):
        """Test that the external link handler is registered as a rich text feature."""
        features_link_types = features.get_link_types()

        self.assertIn("external", features_link_types)
        self.assertIs(features_link_types["external"], ExternalLinkNewTabHandler)


# -----------------------------------------------------------------------------
# Test pre publish hook
# -----------------------------------------------------------------------------


class TestPreventDirectPublish(TestCase):
    """Test that direct publishing can be prevented."""

    def setUp(self):
        """Set up the test case."""
        self.request = self.client.get("/").wsgi_request
        self.page = Page(title="Test page", slug="test-page")

    @override_settings(DISABLE_DIRECT_PUBLISH=True)
    def test_prevents_direct_publishing_when_disabled(self):
        """Test that direct publishing is prevented when disabled."""
        response = prevent_direct_publish(self.request, self.page)
        stored_messages = list(messages.get_messages(self.request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("wagtailadmin_home"))
        self.assertEqual(len(stored_messages), 1)
        self.assertEqual(stored_messages[0].message.strip(), publish_error_message)

    @override_settings(DISABLE_DIRECT_PUBLISH=False)
    def test_allows_direct_publishing_when_enabled(self):
        """Test that direct publishing is allowed when direct publishing is enabled."""
        response = prevent_direct_publish(self.request, self.page)

        self.assertIsNone(response)
        self.assertEqual(list(messages.get_messages(self.request)), [])


# -----------------------------------------------------------------------------
# Test pre bulk action hook
# -----------------------------------------------------------------------------


class TestPreventBulkDirectPublish(TestCase):
    """Test that direct bulk publishing can be prevented."""

    def setUp(self):
        """Set up the test case."""
        self.request = self.client.get("/").wsgi_request
        self.page = Page(title="Test page", slug="test-page")
        self.action = object()

    @override_settings(DISABLE_DIRECT_PUBLISH=True)
    def test_prevents_bulk_publish_when_disabled(self):
        """Test that bulk publishing is prevented when disabled."""

        response = prevent_bulk_direct_publish(self.request, "publish", [self.page], self.action)
        stored_messages = list(messages.get_messages(self.request))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("wagtailadmin_home"))
        self.assertEqual(len(stored_messages), 1)
        self.assertEqual(stored_messages[0].message.strip(), publish_error_message)

    @override_settings(DISABLE_DIRECT_PUBLISH=False)
    def test_allows_bulk_publish_when_enabled(self):
        """Test that bulk publishing is allowed when direct publishing is enabled."""
        response = prevent_bulk_direct_publish(self.request, "publish", [self.page], self.action)

        self.assertIsNone(response)
        self.assertEqual(list(messages.get_messages(self.request)), [])

    def test_allows_other_bulk_actions_irrespectively(self):
        """Test that non-publish bulk actions are allowed regardless publishing settings."""

        with override_settings(DISABLE_DIRECT_PUBLISH=True):
            response = prevent_bulk_direct_publish(self.request, "delete", [self.page], self.action)

        self.assertIsNone(response)
        self.assertEqual(list(messages.get_messages(self.request)), [])

        with override_settings(DISABLE_DIRECT_PUBLISH=False):
            response = prevent_bulk_direct_publish(self.request, "delete", [self.page], self.action)

        self.assertIsNone(response)
        self.assertEqual(list(messages.get_messages(self.request)), [])


# -----------------------------------------------------------------------------
# Test page action menu hook
# -----------------------------------------------------------------------------


class TestRemoveNotAllowedActions(TestCase):
    """Test that disallowed page actions are removed."""

    def setUp(self):
        """Set up the test case."""
        self.user = User.objects.create_user(username="editor", email="editor@example.com")
        self.other_user = User.objects.create_user(username="other", email="other@example.com")

        self.request = self.client.get("/").wsgi_request
        self.request.user = self.user

        self.page = Page(title="Test page", slug="test-page")

        self.publish_item = SimpleNamespace(name="action-publish")
        self.approve_item = SimpleNamespace(name="approve")
        self.reject_item = SimpleNamespace(name="reject")
        self.delete_item = SimpleNamespace(name="delete")

    def _menu_items(self) -> list[SimpleNamespace]:
        """Return a list of menu items for testing."""
        return [self.publish_item, self.approve_item, self.reject_item, self.delete_item]

    def page_with_workflow_state(self, user_id: int) -> SimpleNamespace:
        """Return a mock page with a current workflow state."""
        return SimpleNamespace(current_workflow_state=SimpleNamespace(requested_by_id=user_id))

    @override_settings(DISABLE_DIRECT_PUBLISH=True, DISABLE_SELF_APPROVAL=False)
    def test_removes_publish_when_direct_publishing_disabled(self):
        """Test that publish is removed when direct publishing is disabled."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(menu_items, self.request, {"page": self.page})

        self.assertNotIn(self.publish_item, menu_items)
        self.assertIn(self.approve_item, menu_items)
        self.assertIn(self.reject_item, menu_items)
        self.assertIn(self.delete_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=False, DISABLE_SELF_APPROVAL=False)
    def test_keeps_publish_when_direct_publishing_enabled(self):
        """Test that publish remains when direct publishing is enabled."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(menu_items, self.request, {"page": self.page})

        self.assertIn(self.publish_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=False, DISABLE_SELF_APPROVAL=True)
    def test_removes_approve_and_reject_for_requester(self):
        """Test that approve and reject are removed for the workflow requester."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(
            menu_items, self.request, {"page": self.page_with_workflow_state(self.user.id)}
        )

        self.assertIn(self.publish_item, menu_items)
        self.assertNotIn(self.approve_item, menu_items)
        self.assertNotIn(self.reject_item, menu_items)
        self.assertIn(self.delete_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=False, DISABLE_SELF_APPROVAL=True)
    def test_keeps_approve_and_reject_for_other_user(self):
        """Test that approve and reject remain for another workflow requester."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(
            menu_items, self.request, {"page": self.page_with_workflow_state(self.other_user.id)}
        )

        self.assertIn(self.approve_item, menu_items)
        self.assertIn(self.reject_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=False, DISABLE_SELF_APPROVAL=False)
    def test_keeps_approve_and_reject_when_self_approval_enabled(self):
        """Test that approve and reject remain when self-approval is enabled."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(
            menu_items, self.request, {"page": self.page_with_workflow_state(self.user.id)}
        )

        self.assertIn(self.approve_item, menu_items)
        self.assertIn(self.reject_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=False, DISABLE_SELF_APPROVAL=True)
    def test_keeps_approve_and_reject_without_workflow_state(self):
        """Test that approve and reject remain without a workflow state."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(menu_items, self.request, {"page": self.page})

        self.assertIn(self.approve_item, menu_items)
        self.assertIn(self.reject_item, menu_items)

    @override_settings(DISABLE_DIRECT_PUBLISH=True, DISABLE_SELF_APPROVAL=True)
    def test_removes_both_publish_and_approval_actions_for_requester(self):
        """Test that both publish and approval actions are removed when disallowed."""
        menu_items = self._menu_items()
        remove_not_allowed_actions(
            menu_items, self.request, {"page": self.page_with_workflow_state(self.user.id)}
        )

        self.assertNotIn(self.publish_item, menu_items)
        self.assertNotIn(self.approve_item, menu_items)
        self.assertNotIn(self.reject_item, menu_items)
        self.assertIn(self.delete_item, menu_items)


# -----------------------------------------------------------------------------
# Test homepage panel customization hook
# -----------------------------------------------------------------------------


class TestCustomiseHomepagePanels(SimpleTestCase):
    """Test that the homepage panels are customized."""

    @patch("cms.wagtail_hooks.replace_user_objects_in_workflow_moderation_panel")
    def test_replaces_workflow_moderation_panel(self, replace_panel: MagicMock):
        """Test that the workflow moderation panel is replaced."""
        panels = [object()]
        request = object()
        customise_homepage_panels(request, panels)

        replace_panel.assert_called_once_with(panels)
