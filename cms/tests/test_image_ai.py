"""Tests for AI image disclosure records."""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase
from django.utils import timezone
from wagtail.images import get_image_model

from cms.image_ai import (
    GenerationStatus,
    ImageAIDisclosure,
    PictureLike,
    backfill_image_disclosures,
)
from cms.tests.utils import create_test_image, use_temp_media_root


class TestImageAIDisclosureRules(TestCase):
    """Tests for label and review rules."""

    def setUp(self):
        """Create a Wagtail image and its disclosure."""
        use_temp_media_root(self)
        self.image = create_test_image(title="Rule image", file_name="rule.jpg")
        self.disclosure = ImageAIDisclosure.objects.create(image=self.image)

    def test_unconfirmed_suggestion_does_not_count_as_reviewed(self):
        """A fully AI suggestion is not ready to label until an editor confirms it."""
        self.disclosure.generation_status = GenerationStatus.FULLY_AI
        self.disclosure.picture_like = PictureLike.YES
        self.disclosure.save()

        self.assertTrue(self.disclosure.requires_label)
        self.assertFalse(self.disclosure.is_reviewed)
        self.assertFalse(self.disclosure.is_ready_to_label)

    def test_confirmed_picture_like_ai_image_is_ready_to_label(self):
        """An editor confirmation makes a picture-like AI image ready to label."""
        user = get_user_model().objects.create_user(username="reviewer")
        self.disclosure.generation_status = GenerationStatus.PARTIALLY_AI
        self.disclosure.picture_like = PictureLike.YES
        self.disclosure.reviewed_by = user
        self.disclosure.reviewed_at = timezone.now()
        self.disclosure.save()

        self.assertTrue(self.disclosure.is_reviewed)
        self.assertTrue(self.disclosure.is_ready_to_label)

    def test_non_picture_ai_image_does_not_require_a_label(self):
        """An AI logo or diagram is recorded and left unlabelled."""
        self.disclosure.generation_status = GenerationStatus.FULLY_AI
        self.disclosure.picture_like = PictureLike.NO

        self.assertFalse(self.disclosure.requires_label)
        self.assertFalse(self.disclosure.is_ready_to_label)

    def test_human_image_does_not_require_a_label(self):
        """A human-made image is recorded and left unlabelled."""
        self.disclosure.generation_status = GenerationStatus.NOT_AI
        self.disclosure.picture_like = PictureLike.YES

        self.assertFalse(self.disclosure.requires_label)

    def test_wagtail_image_model_has_no_ai_columns(self):
        """Provenance stays on the sidecar, not on wagtailimages.Image."""
        image_model = get_image_model()

        with self.assertRaises(FieldDoesNotExist):
            image_model._meta.get_field("generation_status")


class TestDisclosureBackfill(TestCase):
    """Tests for the existing-library backfill."""

    def setUp(self):
        """Create one former suggested id and one ordinary image."""
        use_temp_media_root(self)
        self.suggested = create_test_image(
            title="Suggested AI image",
            file_name="suggested.jpg",
            image_id=209,
        )
        self.ordinary = create_test_image(
            title="Ordinary image",
            file_name="ordinary.jpg",
            image_id=1,
        )
        self.suggested.file.open("rb")
        self.suggested_bytes = self.suggested.file.read()
        self.suggested.file.close()
        self.ordinary.file.open("rb")
        self.ordinary_bytes = self.ordinary.file.read()
        self.ordinary.file.close()

    def test_backfill_creates_unconfirmed_rows_without_changing_files(self):
        """Backfill stores decisions and leaves the image bytes unchanged."""
        backfill_image_disclosures(apps, None)
        suggested = ImageAIDisclosure.objects.get(image=self.suggested)
        ordinary = ImageAIDisclosure.objects.get(image=self.ordinary)

        self.assertEqual(suggested.generation_status, GenerationStatus.UNREVIEWED)
        self.assertEqual(suggested.picture_like, PictureLike.UNREVIEWED)
        self.assertIsNone(suggested.reviewed_by)
        self.assertIsNone(suggested.reviewed_at)
        self.assertFalse(suggested.is_reviewed)
        self.assertFalse(suggested.is_ready_to_label)
        self.assertEqual(ordinary.generation_status, GenerationStatus.UNREVIEWED)
        self.assertEqual(ordinary.picture_like, PictureLike.UNREVIEWED)

        self.suggested.file.open("rb")
        self.ordinary.file.open("rb")
        self.assertEqual(self.suggested.file.read(), self.suggested_bytes)
        self.assertEqual(self.ordinary.file.read(), self.ordinary_bytes)
        self.suggested.file.close()
        self.ordinary.file.close()

    def test_backfill_is_idempotent(self):
        """Running the backfill twice does not duplicate disclosures."""
        backfill_image_disclosures(apps, None)
        backfill_image_disclosures(apps, None)

        self.assertEqual(ImageAIDisclosure.objects.count(), 2)
