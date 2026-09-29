"""Tests for the AI provenance fields on the Wagtail image form."""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Model
from django.test import TestCase
from PIL import Image as PILImage
from wagtail.images import get_image_model
from wagtail.images.forms import get_image_form, get_image_multi_form

from cms.forms.image import AIImageForm
from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.tests.utils import create_test_image, use_temp_media_root


def jpeg_upload(name: str = "upload.jpg") -> SimpleUploadedFile:
    """Return a one-pixel JPEG upload."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class TestAIImageForm(TestCase):
    """Tests for provenance validation and disclosure updates."""

    def setUp(self):
        """Create an editor and point media at a temporary directory."""
        use_temp_media_root(self)
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
        }
        data.update(overrides)
        return data

    def test_form_class_uses_the_ai_image_form(self):
        """Add, edit, and multiple-upload forms expose the provenance fields."""
        self.assertTrue(issubclass(self.form_class, AIImageForm))
        multi_form = get_image_multi_form(get_image_model())
        self.assertTrue(issubclass(multi_form, AIImageForm))
        self.assertIn("ai_generated", multi_form(user=self.user).fields)
        self.assertNotIn("file", multi_form(user=self.user).fields)

    def test_new_image_cannot_be_saved_without_a_picture_choice(self):
        """A new image cannot be left unreviewed."""
        form = self.form(
            data=self.base_data(picture_like=""),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("picture_like", form.errors)
        self.assertEqual(ImageAIDisclosure.objects.count(), 0)

    def test_ai_checkbox_requires_full_or_partial(self):
        """Checking AI without an extent is invalid."""
        form = self.form(
            data=self.base_data(ai_generated=True, description="A white square."),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("ai_extent", form.errors)

    def test_picture_like_ai_image_requires_a_description(self):
        """A picture that needs a label also needs accessible description text."""
        form = self.form(
            data=self.base_data(
                ai_generated=True,
                ai_extent=GenerationStatus.FULLY_AI,
                picture_like=PictureLike.YES,
                description="  ",
            ),
            files={"file": jpeg_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_not_ai_image_saves_a_confirmed_disclosure_without_a_description(self):
        """An unchecked AI box stores not-AI and does not label the file."""
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

    def test_confirmed_ai_picture_saves_the_reviewer_and_leaves_the_file_unlabelled(self):
        """A fully AI picture records the decision and does not embed an icon."""
        form = self.form(
            data=self.base_data(
                ai_generated=True,
                ai_extent=GenerationStatus.PARTIALLY_AI,
                description="A microscope photograph with a replaced background.",
            ),
            files={"file": jpeg_upload("partial.jpg")},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save()

        self.assertEqual(image.ai_disclosure.generation_status, GenerationStatus.PARTIALLY_AI)
        self.assertTrue(image.ai_disclosure.requires_label)
        self.assertTrue(image.ai_disclosure.is_ready_to_label)
        self.assertEqual(image.ai_disclosure.labelled_file_hash, "")

    def test_multiple_uploader_save_path_records_the_disclosure(self):
        """The multiple uploader saves the image after the form returns it unsaved."""
        form = self.form(
            data=self.base_data(
                ai_generated=True,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An illustrated laboratory scene.",
            ),
            files={"file": jpeg_upload("multi.jpg")},
        )

        self.assertTrue(form.is_valid(), form.errors)
        image = form.save(commit=False)
        image.uploaded_by_user = self.user
        image.save()

        self.assertEqual(image.ai_disclosure.generation_status, GenerationStatus.FULLY_AI)
        self.assertEqual(image.ai_disclosure.reviewed_by, self.user)

    def test_existing_suggestion_stays_unconfirmed_until_the_editor_saves(self):
        """Opening a suggested image does not confirm it. Saving does, without new pixels."""
        image = create_test_image(
            title="Suggested",
            file_name="suggested.jpg",
            image_id=209,
        )
        ImageAIDisclosure.objects.create(
            image=image,
            generation_status=GenerationStatus.FULLY_AI,
            picture_like=PictureLike.YES,
        )
        image.file.open("rb")
        original_bytes = image.file.read()
        image.file.close()
        form = self.form(data={}, instance=image)
        image.ai_disclosure.refresh_from_db()

        self.assertTrue(form.fields["ai_generated"].initial)
        self.assertEqual(form.fields["ai_extent"].initial, GenerationStatus.FULLY_AI)
        self.assertIsNone(image.ai_disclosure.reviewed_at)

        bound = self.form(
            data=self.base_data(
                title=image.title,
                ai_generated=True,
                ai_extent=GenerationStatus.FULLY_AI,
                description="An elderly man inside a protective dome.",
            ),
            instance=image,
        )
        self.assertTrue(bound.is_valid(), bound.errors)
        bound.save()
        image.refresh_from_db()
        image.file.open("rb")

        self.assertEqual(image.file.read(), original_bytes)
        disclosure = ImageAIDisclosure.objects.get(image=image)
        self.assertEqual(disclosure.reviewed_by, self.user)
        self.assertIsNotNone(disclosure.reviewed_at)
        self.assertEqual(disclosure.labelled_file_hash, "")
        image.file.close()
