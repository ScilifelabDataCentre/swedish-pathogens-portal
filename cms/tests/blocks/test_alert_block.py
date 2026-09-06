"""Unit tests for ``AlertBlock`` validation and rendering."""

from django.test import SimpleTestCase
from wagtail.blocks import StructBlockValidationError

from cms.blocks.alerts import AlertBlock


class TestAlertBlock(SimpleTestCase):
    """Tests for the AlertBlock."""

    def setUp(self):
        """Set up test data."""
        self.block = AlertBlock()

    def test_valid_data_passes_validation(self):
        """Test that valid data passes validation."""
        value = self.block.to_python(
            {
                "message": "<p>Hello world</p>",
                "alert_type": "success",
            }
        )

        result = self.block.clean(value)

        self.assertEqual(result["message"].source, "<p>Hello world</p>")
        self.assertEqual(result["alert_type"], "success")

    def test_default_alert_type_is_used(self):
        """Test that the default alert type is used when not provided."""
        value = self.block.to_python(
            {
                "message": "<p>Hello world</p>",
            }
        )

        result = self.block.clean(value)

        # ChoiceBlock default should be applied
        self.assertEqual(result["alert_type"], "info")

    def test_invalid_alert_type_raises_error(self):
        """Test that an invalid alert type raises a validation error."""
        value = self.block.to_python(
            {
                "message": "<p>Hello world</p>",
                "alert_type": "invalid",
            }
        )

        with self.assertRaises(StructBlockValidationError) as context:
            self.block.clean(value)

        self.assertIn("alert_type", context.exception.block_errors)

    def test_message_is_required(self):
        """Test that the message field is required."""
        value = self.block.to_python(
            {
                "alert_type": "info",
            }
        )

        with self.assertRaises(StructBlockValidationError) as context:
            self.block.clean(value)

        self.assertIn("message", context.exception.block_errors)

    def test_render_outputs_expected_html(self):
        """Test that the block renders the expected HTML."""
        value = self.block.to_python(
            {
                "message": "<p>Alert message</p>",
                "alert_type": "warning",
            }
        )

        html = self.block.render(value)

        self.assertIn("Alert message", html)
        self.assertIn("alert-warning", html)
