"""Test the SppSettings model."""

from django.test import TestCase

from cms.site_settings.spp_settings import SppSettings


class TestSppSettingsModel(TestCase):
    """Test case for the SppSettings model."""

    def test_default_values(self):
        """Test that the default values for the SPP settings fields are as expected."""
        settings = SppSettings()

        self.assertFalse(settings.disable_direct_publishing)
        self.assertFalse(settings.disable_self_approval)

    def test_values_can_be_persisted(self):
        """Test that the SPP settings fields can be persisted to the database."""
        settings = SppSettings.objects.create(
            disable_direct_publishing=True, disable_self_approval=True
        )
        settings.refresh_from_db()

        self.assertTrue(settings.disable_direct_publishing)
        self.assertTrue(settings.disable_self_approval)
