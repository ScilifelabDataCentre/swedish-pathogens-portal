"""Tests for embedding official EU icons into confirmed AI images."""

import hashlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from PIL import Image as PILImage
from wagtail.images import get_image_model
from wagtail.images.models import AbstractImage

from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.services.ai_image_labelling import (
    ICON_DIR,
    LABEL_VERSION,
    OFFICIAL_ICON_SHA256,
    AIImageLabellingError,
    LabelOutcome,
    UnconfirmedDisclosureError,
    UnsupportedImageError,
    label_image,
)
from cms.tests.utils import create_test_image, use_temp_media_root


def jpeg_bytes(size: tuple[int, int], color: str, *, exif: bytes | None = None) -> bytes:
    """Return JPEG bytes of one solid colour.

    Args:
        size: Image width and height.
        color: Pillow colour name.
        exif: Optional EXIF payload.

    Returns:
        Encoded JPEG bytes.
    """
    buffer = io.BytesIO()
    image = PILImage.new("RGB", size, color)
    if exif is None:
        image.save(buffer, format="JPEG", quality=95)
    else:
        image.save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def png_bytes(size: tuple[int, int], color: str) -> bytes:
    """Return PNG bytes of one solid colour.

    Args:
        size: Image width and height.
        color: Pillow colour name.

    Returns:
        Encoded PNG bytes.
    """
    buffer = io.BytesIO()
    PILImage.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def icon_channel_bounds(content: bytes) -> tuple[int, int]:
    """Return the darkest and lightest channel in the top-right icon area.

    Args:
        content: Labelled image bytes.

    Returns:
        Minimum and maximum channel values in that area.
    """
    with PILImage.open(io.BytesIO(content)) as image:
        width, height = image.size
        area = image.convert("RGB").crop((int(width * 0.75), 0, width, int(height * 0.25)))
        extrema = area.getextrema()
    darkest = min(channel[0] for channel in extrema)
    lightest = max(channel[1] for channel in extrema)
    return darkest, lightest


class TestOfficialIconFiles(SimpleTestCase):
    """Tests that the bundled icons are the Commission originals."""

    def test_bundled_files_match_the_commission_checksums(self):
        """Every retained icon file matches the published SHA-256."""
        for name, expected in OFFICIAL_ICON_SHA256.items():
            digest = hashlib.sha256((ICON_DIR / name).read_bytes()).hexdigest()
            self.assertEqual(digest, expected, name)


class TestAIImageLabelling(TestCase):
    """Tests for stamp, skip, archive, and rejection behaviour."""

    def setUp(self):
        """Point media and the pristine archive at temporary directories."""
        self.media = use_temp_media_root(self)
        self.archive = tempfile.TemporaryDirectory()
        self.addCleanup(self.archive.cleanup)
        override = override_settings(AI_IMAGE_ARCHIVE_ROOT=self.archive.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user(username="reviewer")

    def store(self, name: str, content: bytes, content_type: str):
        """Save a Wagtail image from raw file bytes.

        Args:
            name: Stored filename.
            content: File bytes.
            content_type: Upload content type.

        Returns:
            Saved Wagtail image.
        """
        image_model = get_image_model()
        return image_model.objects.create(
            title=name,
            file=SimpleUploadedFile(name, content, content_type=content_type),
        )

    def confirm(
        self,
        image: AbstractImage,
        status: str = GenerationStatus.FULLY_AI,
        picture: str = PictureLike.YES,
        *,
        reviewed: bool = True,
    ) -> ImageAIDisclosure:
        """Attach a disclosure row to an image.

        Args:
            image: Saved Wagtail image.
            status: Generation status.
            picture: Picture-like choice.
            reviewed: Whether the row has a reviewer and timestamp.

        Returns:
            Saved disclosure.
        """
        return ImageAIDisclosure.objects.create(
            image=image,
            generation_status=status,
            picture_like=picture,
            reviewed_by=self.user if reviewed else None,
            reviewed_at=timezone.now() if reviewed else None,
        )

    def archive_files(self) -> list[Path]:
        """Return files written to the pristine archive.

        Returns:
            Archive file paths.
        """
        return [path for path in Path(self.archive.name).rglob("*") if path.is_file()]

    def test_unconfirmed_suggestion_is_refused(self):
        """A suggested AI image is not stamped before an editor confirms it."""
        image = self.store("suggested.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image, reviewed=False)
        before = Path(image.file.path).read_bytes()

        with self.assertRaises(UnconfirmedDisclosureError):
            label_image(image)

        self.assertEqual(Path(image.file.path).read_bytes(), before)
        self.assertEqual(self.archive_files(), [])

    def test_missing_disclosure_is_refused(self):
        """Labelling requires a disclosure row."""
        image = self.store("plain.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")

        with self.assertRaises(AIImageLabellingError):
            label_image(image)

    def test_not_ai_image_is_skipped(self):
        """A confirmed not-AI image keeps its original bytes."""
        image = self.store("photo.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image, status=GenerationStatus.NOT_AI)
        before = Path(image.file.path).read_bytes()

        result = label_image(image)

        self.assertEqual(result.outcome, LabelOutcome.NOT_REQUIRED)
        self.assertEqual(Path(image.file.path).read_bytes(), before)
        self.assertEqual(self.archive_files(), [])

    def test_non_picture_ai_image_is_skipped(self):
        """An AI logo or diagram is recorded and left unlabelled."""
        image = self.store("logo.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image, picture=PictureLike.NO)
        before = Path(image.file.path).read_bytes()

        result = label_image(image)

        self.assertEqual(result.outcome, LabelOutcome.NOT_REQUIRED)
        self.assertEqual(Path(image.file.path).read_bytes(), before)

    def test_reviewed_unreviewed_status_is_skipped(self):
        """An explicit unreviewed status does not change pixels."""
        image = self.store("pending.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image, status=GenerationStatus.UNREVIEWED, picture=PictureLike.UNREVIEWED)
        before = Path(image.file.path).read_bytes()

        result = label_image(image)

        self.assertEqual(result.outcome, LabelOutcome.NOT_REQUIRED)
        self.assertEqual(Path(image.file.path).read_bytes(), before)

    def test_fully_ai_image_gets_the_black_icon_on_a_light_background(self):
        """A light fully AI image is archived and stamped with the black icon."""
        image = self.store("full.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        disclosure = self.confirm(image)
        path = Path(image.file.path)
        before = path.read_bytes()

        result = label_image(image)

        after = path.read_bytes()
        disclosure.refresh_from_db()
        archived = self.archive_files()
        darkest, _lightest = icon_channel_bounds(after)
        self.assertEqual(result.outcome, LabelOutcome.LABELLED)
        self.assertNotEqual(after, before)
        self.assertTrue(after.startswith(b"\xff\xd8"))
        self.assertLess(darkest, 80)
        self.assertEqual(result.file_hash, hashlib.sha256(after).hexdigest())
        self.assertEqual(disclosure.labelled_file_hash, result.file_hash)
        self.assertEqual(disclosure.label_version, LABEL_VERSION)
        self.assertIsNotNone(disclosure.labelled_at)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), before)
        self.assertFalse(archived[0].resolve().is_relative_to(self.media.resolve()))

    def test_partial_ai_image_gets_the_white_icon_on_a_dark_background(self):
        """A dark partially AI image keeps PNG format and uses the white icon."""
        image = self.store("partial.png", png_bytes((800, 500), "black"), "image/png")
        self.confirm(image, status=GenerationStatus.PARTIALLY_AI)
        path = Path(image.file.path)
        before = path.read_bytes()

        result = label_image(image)

        after = path.read_bytes()
        _darkest, lightest = icon_channel_bounds(after)
        self.assertEqual(result.outcome, LabelOutcome.LABELLED)
        self.assertNotEqual(after, before)
        self.assertTrue(after.startswith(b"\x89PNG"))
        self.assertGreater(lightest, 200)

    def test_fully_and_partial_icons_differ(self):
        """The two EU icons are not interchangeable."""
        full = self.store("full-compare.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        partial = self.store(
            "partial-compare.jpg",
            jpeg_bytes((800, 500), "white"),
            "image/jpeg",
        )
        self.confirm(full)
        self.confirm(partial, status=GenerationStatus.PARTIALLY_AI)

        label_image(full)
        label_image(partial)

        self.assertNotEqual(
            Path(full.file.path).read_bytes(),
            Path(partial.file.path).read_bytes(),
        )

    def test_second_run_does_not_stamp_another_icon(self):
        """A current label is left unchanged, including the pristine archive."""
        image = self.store("twice.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        disclosure = self.confirm(image)
        label_image(image)
        stamped = Path(image.file.path).read_bytes()
        labelled_at = ImageAIDisclosure.objects.get(pk=disclosure.pk).labelled_at

        result = label_image(image)

        self.assertEqual(result.outcome, LabelOutcome.ALREADY_LABELLED)
        self.assertEqual(Path(image.file.path).read_bytes(), stamped)
        self.assertEqual(len(self.archive_files()), 1)
        self.assertEqual(ImageAIDisclosure.objects.get(pk=disclosure.pk).labelled_at, labelled_at)

    def test_animated_image_is_rejected_without_replacement(self):
        """An animated file is out of scope and stays byte-for-byte unchanged."""
        image = self.store("still.jpg", jpeg_bytes((320, 200), "white"), "image/jpeg")
        self.confirm(image)
        frames = [PILImage.new("RGB", (320, 200), color) for color in ("white", "black")]
        buffer = io.BytesIO()
        frames[0].save(
            buffer,
            format="WEBP",
            save_all=True,
            append_images=[frames[1]],
            duration=100,
        )
        path = Path(image.file.path)
        animated = buffer.getvalue()
        path.write_bytes(animated)

        with self.assertRaises(UnsupportedImageError):
            label_image(image)

        self.assertEqual(path.read_bytes(), animated)
        self.assertEqual(self.archive_files(), [])

    def test_unsupported_format_is_rejected_without_replacement(self):
        """A non-JPEG, PNG, or WebP file is not replaced."""
        image = self.store("photo.jpg", jpeg_bytes((80, 80), "red"), "image/jpeg")
        self.confirm(image)
        buffer = io.BytesIO()
        PILImage.new("RGB", (80, 80), "red").save(buffer, format="BMP")
        path = Path(image.file.path)
        bmp = buffer.getvalue()
        path.write_bytes(bmp)

        with self.assertRaises(UnsupportedImageError):
            label_image(image)

        self.assertEqual(path.read_bytes(), bmp)
        self.assertEqual(self.archive_files(), [])

    def test_tiny_image_is_rejected_without_replacement(self):
        """An image that cannot hold the icon and its padding is left unchanged."""
        image = create_test_image(title="Tiny", file_name="tiny.jpg")
        self.confirm(image)
        before = Path(image.file.path).read_bytes()

        with self.assertRaises(UnsupportedImageError):
            label_image(image)

        self.assertEqual(Path(image.file.path).read_bytes(), before)

    def test_renditions_are_deleted_after_labelling(self):
        """Old renditions are removed so the next view rebuilds them from the label."""
        image = self.store("rendition.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image)
        rendition = image.get_rendition("width-100")
        rendition_path = Path(rendition.file.path)

        label_image(image)

        self.assertEqual(image.renditions.count(), 0)
        self.assertFalse(rendition_path.exists())

    def test_database_failure_puts_the_public_file_back(self):
        """A failed disclosure save restores the bytes that were on disk."""
        image = self.store("restore.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image)
        before = Path(image.file.path).read_bytes()

        with (
            patch(
                "cms.services.ai_image_labelling._record_label",
                side_effect=RuntimeError("database unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            label_image(image)

        self.assertEqual(Path(image.file.path).read_bytes(), before)
        self.assertEqual(image.ai_disclosure.labelled_file_hash, "")

    def test_exif_orientation_is_applied_before_the_icon_is_placed(self):
        """A sideways JPEG is turned upright before the icon is embedded."""
        sideways = PILImage.new("RGB", (240, 80), "white")
        exif = sideways.getexif()
        exif[274] = 6
        image = self.store("sideways.jpg", jpeg_bytes((40, 40), "white"), "image/jpeg")
        self.confirm(image)
        path = Path(image.file.path)
        path.write_bytes(jpeg_bytes((240, 80), "white", exif=exif.tobytes()))

        label_image(image)

        image.refresh_from_db()
        with PILImage.open(path) as stamped:
            self.assertEqual(stamped.size, (80, 240))
        self.assertEqual((image.width, image.height), (80, 240))

    def test_archive_inside_media_is_refused(self):
        """The pristine copy is not written into the public media tree."""
        image = self.store("public.jpg", jpeg_bytes((800, 500), "white"), "image/jpeg")
        self.confirm(image)
        before = Path(image.file.path).read_bytes()
        nested = self.media / "ai-archive"

        with (
            override_settings(AI_IMAGE_ARCHIVE_ROOT=str(nested)),
            self.assertRaises(AIImageLabellingError),
        ):
            label_image(image)

        self.assertEqual(Path(image.file.path).read_bytes(), before)
        self.assertFalse(nested.exists())
