"""Tests for ``CaptionedImageFormat`` in ``cms.image_formats``."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.image_formats import CaptionedImageFormat


def build_format(name: str) -> CaptionedImageFormat:
    """Build a CaptionedImageFormat instance with the given name."""
    return CaptionedImageFormat(
        name=name,
        label="Captioned",
        classname="richtext-image",
        filter_spec="original",
    )


class TestCaptionedImageFormat(SimpleTestCase):
    """Tests for the CaptionedImageFormat class."""

    def setUp(self):
        """Set up test data."""
        self.rendition = SimpleNamespace(
            url="/fake.jpg",
            width=800,
            height=600,
        )

        self.image = MagicMock()
        self.image.title = "Default title"
        self.image.get_rendition.return_value = self.rendition

    @patch("cms.image_formats.render_to_string")
    def test_alt_falls_back_to_image_title(self, mock_render: MagicMock):
        """Test that the alt text falls back to the image title when alt text is empty."""
        mock_render.return_value = "<html>ok</html>"

        fmt = build_format("captioned_full_width")
        fmt.image_to_html(image=self.image, alt_text="")

        context = mock_render.call_args.kwargs["context"]

        # The alt text should fall back to the image title set in the setUp method
        self.assertEqual(context["alt_text"], "Default title")

    @patch("cms.image_formats.render_to_string")
    def test_alignment_and_alt_text(self, mock_render: MagicMock):
        """Test alignment class and alt text logic for different formats."""
        mock_render.return_value = "<html>ok</html>"

        cases = [
            (
                "captioned_full_width",
                "Default aligned image",
                "float-none",
            ),
            (
                "captioned_float_left",
                "Left aligned image",
                "float-left",
            ),
            (
                "captioned_float_right",
                "Right aligned image",
                "float-right",
            ),
        ]

        for name, alt_text, expected_alignment in cases:
            with self.subTest(format=name):
                fmt = build_format(name)

                fmt.image_to_html(
                    image=self.image,
                    alt_text=alt_text,
                )

                context = mock_render.call_args.kwargs["context"]

                self.assertEqual(context["alignment_class"], expected_alignment)
                self.assertEqual(context["alt_text"], alt_text)

    @patch("cms.image_formats.render_to_string")
    def test_rendition_filter_is_used(self, mock_render: MagicMock):
        """Test that the image rendition is generated with the correct filter spec."""
        mock_render.return_value = "<html>ok</html>"

        fmt = build_format("captioned_float_left")
        fmt.image_to_html(image=self.image, alt_text="Alt text")

        self.image.get_rendition.assert_called_once()

        filter_spec = self.image.get_rendition.call_args.args[0]

        # Verify your custom filter pipeline is applied
        self.assertEqual(filter_spec, "original|format-webp")

    def test_image_to_html_renders_output(self):
        """Test that the image_to_html method renders html as expected."""
        fmt = build_format("captioned_float_left")

        html = fmt.image_to_html(image=self.image, alt_text="Custom alt")

        self.assertIsInstance(html, str)
        self.assertIn("Custom alt", html)
        self.assertIn("float-left", html)
        self.assertIn("<img", html)
        self.assertIn("<figure", html)
        self.assertIn("<figcaption", html)
        self.assertNotIn("AI-generated image:", html)
        self.assertNotIn("AI-modified image:", html)

    def test_confirmed_ai_alt_is_prefixed_and_caption_stays_semantic(self):
        """A confirmed picture-like AI image prefixes alt text and leaves the caption."""
        fmt = build_format("captioned_full_width")
        self.image.description = "An elderly person inside a protective dome"
        self.image.ai_disclosure = ImageAIDisclosure(
            generation_status=GenerationStatus.FULLY_AI,
            picture_like=PictureLike.YES,
            reviewed_by_id=1,
            reviewed_at=datetime(2026, 9, 29, tzinfo=UTC),
        )

        html = fmt.image_to_html(image=self.image, alt_text="Editor alt")

        self.assertIn(
            'alt="AI-generated image: An elderly person inside a protective dome"',
            html,
        )
        self.assertIn(">Editor alt</figcaption>", html)
