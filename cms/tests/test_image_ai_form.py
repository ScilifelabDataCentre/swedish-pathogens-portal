"""Tests for the AI provenance fields on the Wagtail image form."""

import hashlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Model
from django.forms import ValidationError
from django.test import TestCase, override_settings
from PIL import Image as PILImage
from wagtail.images import get_image_model
from wagtail.images.forms import get_image_form, get_image_multi_form

from cms.forms.image import AIImageForm
from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.services.ai_image_labelling import LABEL_VERSION, UnsupportedImageError
from cms.tests.utils import create_test_image, use_temp_media_root

LARGE = (800, 500)


def jpeg_upload(
    name: str = "upload.jpg",
    size: tuple[int, int] = (1, 1),
    color: str = "white",
) -> SimpleUploadedFile:
    """Return a solid JPEG upload.

    Args:
        name: Upload filename.
        size: Image width and height.
        color: Pillow colour name.

    Returns:
        In-memory JPEG upload.
    """
    buffer = io.BytesIO()
    PILImage.new("RGB", size, color=color).save(buffer, format="JPEG", quality=95)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class TestAIImageForm(TestCase):
    """Tests for provenance validation and disclosure updates."""

    def setUp(self):
        """Create an editor and point media and the archive at temporary directories."""
        self.media = use_temp_media_root(self)
        self.archive = tempfile.TemporaryDirectory()
        self.addCleanup(self.archive.cleanup)
        override = override_settings(AI_IMAGE_ARCHIVE_ROOT=self.archive.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_superuser(
            username="image-editor",
            email="image-editor@example.com",
            password="password",  # noqa: S106
        )
        self.form_class = get_image_form(get_image_model())

    def form(
        self,
        *,
        data: dict[str, str | bool],
        files: dict[str, SimpleUploadedFile] | None = None,
        instance: Model | None = None,
    ):
        """Build a bound image form for the test editor."""
        return self.form_class(
            data=data,
            files=files,
            instance=instance,
            user=self.user,
        )

    def base_data(self, **overrides: str | bool) -> dict[str, str | bool]:
        """Return a valid not-AI picture submission."""
        data: dict[str, str | bool] = {
            "title": "Test upload",
            "description": "",
            "tags": "",
            "picture_like": PictureLike.YES,
            "ai_extent": GenerationStatus.NOT_AI,
        }
        data.update(overrides)
        return data

    def test_form_class_uses_the_ai_image_form(self):
        """Add, edit, and multiple-upload forms expose the provenance fields."""
        self.assertTrue(issubclass(self.form_class, AIImageForm))
        multi_form = get_image_multi_form(get_image_model())
        self.assertTrue(issubclass(multi_form, AIImageForm))
        fields = multi_form(user=self.user).fields
        self.assertNotIn("ai_generated", fields)
        self.assertTrue(fields["ai_extent"].required)
        self.assertNotIn("file", fields)

    def test_new_image_cannot_be_saved_without_a_picture_choice(self):
        """A new image cannot be left unreviewed."""
        form = self.form(
            data=self.base_data(picture_like=""),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("picture_like", form.errors)
        self.assertEqual(ImageAIDisclosure.objects.count(), 0)

    def test_ai_use_is_required(self):
        """A new image cannot be saved until the editor chooses how AI was used."""
        form = self.form(
            data=self.base_data(ai_extent="", description="A white square."),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("ai_extent", form.errors)

    def test_picture_like_ai_image_requires_a_description(self):
        """A picture that needs a label also needs accessible description text."""
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                picture_like=PictureLike.YES,
                description="  ",
            ),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_not_ai_image_saves_a_confirmed_disclosure_without_a_description(self):
        """A not-AI choice stores that decision and does not label the file."""
        upload = jpeg_upload()
        form = self.form(
            data=self.base_data(picture_like=PictureLike.NO),
            files={"file": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save()
        disclosure = image.ai_disclosure

        self.assertEqual(disclosure.generation_status, GenerationStatus.NOT_AI)
        self.assertEqual(disclosure.picture_like, PictureLike.NO)
        self.assertEqual(disclosure.reviewed_by, self.user)
        self.assertIsNotNone(disclosure.reviewed_at)
        self.assertEqual(disclosure.labelled_file_hash, "")
        self.assertIsNone(disclosure.labelled_at)
        image.file.open("rb")
        self.assertTrue(image.file.read().startswith(b"\xff\xd8"))
        image.file.close()

    def test_tiny_ai_picture_is_rejected_on_the_form(self):
        """A picture-like AI file that cannot hold the icon is not saved."""
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.PARTIALLY_AI,
                description="A microscope photograph with a replaced background.",
            ),
            files={"file": jpeg_upload("partial.jpg")},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)
        self.assertIn("too small", form.errors["file"][0])
        self.assertEqual(get_image_model().objects.count(), 0)
        self.assertEqual(ImageAIDisclosure.objects.count(), 0)

    def test_in_scope_upload_embeds_the_icon(self):
        """One save stores the image, the decision, the archive, and the icon."""
        upload = jpeg_upload("full.jpg", LARGE)
        original = upload.read()
        upload.seek(0)
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save()
        labelled = Path(image.file.path).read_bytes()
        disclosure = ImageAIDisclosure.objects.get(image=image)
        archived = [path for path in Path(self.archive.name).rglob("*") if path.is_file()]

        self.assertEqual(disclosure.generation_status, GenerationStatus.FULLY_AI)
        self.assertTrue(disclosure.is_ready_to_label)
        self.assertEqual(disclosure.reviewed_by, self.user)
        self.assertEqual(disclosure.label_version, LABEL_VERSION)
        self.assertEqual(disclosure.labelled_file_hash, hashlib.sha256(labelled).hexdigest())
        self.assertIsNotNone(disclosure.labelled_at)
        self.assertNotEqual(labelled, original)
        self.assertTrue(labelled.startswith(b"\xff\xd8"))
        self.assertEqual(archived[0].read_bytes(), original)
        self.assertFalse(archived[0].resolve().is_relative_to(self.media.resolve()))

    def test_second_save_does_not_stamp_another_icon(self):
        """Saving the same decision again leaves the labelled file unchanged."""
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": jpeg_upload("twice.jpg", LARGE)},
        )
        image = form.save()
        stamped = Path(image.file.path).read_bytes()
        labelled_at = ImageAIDisclosure.objects.get(image=image).labelled_at

        again = self.form(
            data=self.base_data(
                title=image.title,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            instance=image,
        )
        self.assertTrue(again.is_valid(), again.errors)
        again.save()

        self.assertEqual(Path(image.file.path).read_bytes(), stamped)
        self.assertEqual(ImageAIDisclosure.objects.get(image=image).labelled_at, labelled_at)
        self.assertEqual(
            len([path for path in Path(self.archive.name).rglob("*") if path.is_file()]),
            1,
        )

    def test_ai_diagram_is_saved_without_changing_pixels(self):
        """An AI image that is not picture-like keeps its original file."""
        upload = jpeg_upload("logo.jpg", LARGE)
        original = upload.read()
        upload.seek(0)
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                picture_like=PictureLike.NO,
            ),
            files={"file": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save()
        disclosure = ImageAIDisclosure.objects.get(image=image)

        self.assertEqual(disclosure.picture_like, PictureLike.NO)
        self.assertFalse(disclosure.requires_label)
        self.assertEqual(disclosure.labelled_file_hash, "")
        self.assertEqual(Path(image.file.path).read_bytes(), original)

    def test_changing_an_existing_image_to_ai_labels_that_file(self):
        """An editor can mark an existing picture as AI and label it in the same save."""
        image = self.form(
            data=self.base_data(picture_like=PictureLike.YES),
            files={"file": jpeg_upload("existing.jpg", LARGE)},
        ).save()
        before = Path(image.file.path).read_bytes()
        form = self.form(
            data=self.base_data(
                title=image.title,
                ai_extent=GenerationStatus.PARTIALLY_AI,
                description="A photograph with an AI-generated background.",
            ),
            instance=image,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        disclosure = ImageAIDisclosure.objects.get(image=image)

        self.assertEqual(disclosure.generation_status, GenerationStatus.PARTIALLY_AI)
        self.assertEqual(disclosure.label_version, LABEL_VERSION)
        self.assertNotEqual(Path(image.file.path).read_bytes(), before)

    def test_replacing_a_labelled_file_labels_the_replacement(self):
        """A new file on an in-scope image is archived and labelled before it is ready."""
        image = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": jpeg_upload("first.jpg", LARGE, "white")},
        ).save()
        first = Path(image.file.path).read_bytes()
        replacement = jpeg_upload("second.jpg", LARGE, "black")
        raw_replacement = replacement.read()
        replacement.seek(0)
        form = self.form(
            data=self.base_data(
                title=image.title,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": replacement},
            instance=image,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        image.refresh_from_db()
        current = Path(image.file.path).read_bytes()

        self.assertNotEqual(current, first)
        self.assertNotEqual(current, raw_replacement)
        self.assertEqual(
            ImageAIDisclosure.objects.get(image=image).labelled_file_hash,
            hashlib.sha256(current).hexdigest(),
        )

    def test_labelling_failure_does_not_leave_a_new_unlabelled_ai_image(self):
        """A failed label deletes the new image instead of leaving it selectable."""
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": jpeg_upload("failed.jpg", LARGE)},
        )
        self.assertTrue(form.is_valid(), form.errors)

        with (
            patch(
                "cms.forms.image.label_image",
                side_effect=UnsupportedImageError("archive unavailable"),
            ),
            self.assertRaises(ValidationError),
        ):
            form.save()

        self.assertEqual(get_image_model().objects.count(), 0)
        self.assertEqual(ImageAIDisclosure.objects.count(), 0)

    def test_labelling_failure_keeps_the_previous_decision(self):
        """A failed relabel leaves the existing image and its previous disclosure."""
        image = self.form(
            data=self.base_data(picture_like=PictureLike.YES),
            files={"file": jpeg_upload("kept.jpg", LARGE)},
        ).save()
        before = Path(image.file.path).read_bytes()
        form = self.form(
            data=self.base_data(
                title=image.title,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            instance=image,
        )

        with (
            patch(
                "cms.forms.image.label_image",
                side_effect=UnsupportedImageError("archive unavailable"),
            ),
            self.assertRaises(ValidationError),
        ):
            form.save()

        disclosure = ImageAIDisclosure.objects.get(image=image)
        self.assertEqual(disclosure.generation_status, GenerationStatus.NOT_AI)
        self.assertEqual(disclosure.labelled_file_hash, "")
        self.assertEqual(Path(image.file.path).read_bytes(), before)

    def test_multiple_uploader_save_path_labels_after_the_image_is_saved(self):
        """The multiple uploader saves the image, then the wrapped save labels it."""
        form = self.form(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": jpeg_upload("multi.jpg", LARGE)},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save(commit=False)
        image.uploaded_by_user = self.user
        image.save()
        disclosure = ImageAIDisclosure.objects.get(image=image)

        self.assertEqual(disclosure.generation_status, GenerationStatus.FULLY_AI)
        self.assertEqual(disclosure.reviewed_by, self.user)
        self.assertEqual(disclosure.label_version, LABEL_VERSION)

    def test_multiple_uploader_rejects_a_file_attached_after_validation(self):
        """The create-from-upload step still refuses a file that cannot be labelled."""
        form = get_image_multi_form(get_image_model())(
            data=self.base_data(
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            instance=get_image_model()(),
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.file.save("tiny.jpg", jpeg_upload("tiny.jpg"), save=False)

        with self.assertRaises(ValidationError):
            form.save()

        self.assertEqual(get_image_model().objects.count(), 0)
        self.assertEqual(ImageAIDisclosure.objects.count(), 0)

    def test_existing_suggestion_stays_unconfirmed_until_the_editor_saves(self):
        """Opening a suggested image does not confirm it. Saving labels it."""
        image = create_test_image(
            title="Suggested",
            file_name="suggested.jpg",
            image_id=209,
        )
        Path(image.file.path).write_bytes(jpeg_upload("suggested.jpg", LARGE).read())
        ImageAIDisclosure.objects.create(
            image=image,
            generation_status=GenerationStatus.FULLY_AI,
            picture_like=PictureLike.YES,
        )
        before = Path(image.file.path).read_bytes()
        form = self.form(data={}, instance=image)
        image.ai_disclosure.refresh_from_db()

        self.assertIsNone(form.fields["ai_extent"].initial)
        self.assertIsNone(form.fields["picture_like"].initial)
        self.assertIsNone(image.ai_disclosure.reviewed_at)

        bound = self.form(
            data=self.base_data(
                title=image.title,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An elderly man inside a protective dome.",
            ),
            instance=image,
        )
        self.assertTrue(bound.is_valid(), bound.errors)
        bound.save()
        disclosure = ImageAIDisclosure.objects.get(image=image)

        self.assertNotEqual(Path(image.file.path).read_bytes(), before)
        self.assertEqual(disclosure.reviewed_by, self.user)
        self.assertIsNotNone(disclosure.reviewed_at)
        self.assertEqual(disclosure.label_version, LABEL_VERSION)
