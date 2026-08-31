"""Test the SppSettings services."""

from django.test import TestCase

from cms.services.spp_settings import direct_publishing_disabled, self_approval_disabled
from cms.site_settings.spp_settings import SppSettings


class TestDirectPublishingDisabled(TestCase):
    """Test the direct publishing disabled service."""

    def test_returns_false_by_default(self):
        """Test that direct publishing is enabled by default."""
        self.assertFalse(direct_publishing_disabled())

    def test_returns_set_value(self):
        """Test that direct publishing is disabled when configured."""
        settings = SppSettings.load()
        settings.disable_direct_publishing = True
        settings.save()

        self.assertTrue(direct_publishing_disabled())

        settings.disable_direct_publishing = False
        settings.save()

        self.assertFalse(direct_publishing_disabled())


class TestSelfApprovalDisabled(TestCase):
    """Test the self approval disabled service."""

    def test_returns_false_by_default(self):
        """Test that self approval is enabled by default."""
        self.assertFalse(self_approval_disabled())

    def test_returns_set_value(self):
        """Test that self approval is disabled when configured."""
        settings = SppSettings.load()
        settings.disable_self_approval = True
        settings.save()

        self.assertTrue(self_approval_disabled())

        settings.disable_self_approval = False
        settings.save()

        self.assertFalse(self_approval_disabled())
