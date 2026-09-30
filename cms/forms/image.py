"""Wagtail image form that records AI provenance and labels on save."""

from collections.abc import Callable
from pathlib import Path

from django import forms
from django.db import transaction
from django.db.models import Model
from django.utils import timezone
from PIL import Image as PILImage
from wagtail.images.forms import BaseImageForm

from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike
from cms.services.ai_image_labelling import (
    AIImageLabellingError,
    ensure_image_can_be_labelled,
    label_image,
)

AI_EXTENT_CHOICES = [
    (GenerationStatus.FULLY_AI, "Fully AI-generated"),
    (GenerationStatus.PARTIALLY_AI, "Partially AI-modified"),
]
PICTURE_LIKE_CHOICES = [
    (PictureLike.YES, "Yes"),
    (PictureLike.NO, "No — logo, chart, diagram, or animation"),
]
PROVENANCE_FIELDS = ("ai_generated", "ai_extent", "picture_like")


class AIImageForm(BaseImageForm):
    """Add AI provenance questions to every Wagtail image create and edit form.

    Saving records the signed-in editor as the reviewer. When that decision
    requires a label, the same save embeds the official EU icon.
    """

    ai_generated = forms.BooleanField(
        required=False,
        label="This image was created or changed using AI",
    )
    ai_extent = forms.ChoiceField(
        required=False,
        choices=AI_EXTENT_CHOICES,
        widget=forms.RadioSelect,
        label="How was AI used?",
        help_text="Required when the image was created or changed using AI.",
    )
    picture_like = forms.ChoiceField(
        required=True,
        choices=PICTURE_LIKE_CHOICES,
        widget=forms.RadioSelect,
        label="Could someone interpret this as a picture?",
    )

    def __init__(self, *args, **kwargs) -> None:
        """Keep the editor for the review audit and show any saved decision."""
        self.reviewer = kwargs.get("user")
        super().__init__(*args, **kwargs)
        self._set_disclosure_initials()
        self._order_provenance_fields()

    def _set_disclosure_initials(self) -> None:
        """Show a saved decision. An unreviewed image stays unanswered."""
        if not self.instance.pk:
            return
        try:
            disclosure = self.instance.ai_disclosure
        except ImageAIDisclosure.DoesNotExist:
            return
        if disclosure.generation_status in {
            GenerationStatus.FULLY_AI,
            GenerationStatus.PARTIALLY_AI,
        }:
            self.fields["ai_generated"].initial = True
            self.fields["ai_extent"].initial = disclosure.generation_status
        elif disclosure.generation_status == GenerationStatus.NOT_AI:
            self.fields["ai_generated"].initial = False
        if disclosure.picture_like in {PictureLike.YES, PictureLike.NO}:
            self.fields["picture_like"].initial = disclosure.picture_like

    def _order_provenance_fields(self) -> None:
        """Place the provenance questions after the image description."""
        remaining = [name for name in self.fields if name not in PROVENANCE_FIELDS]
        anchor = "description" if "description" in remaining else "title"
        index = remaining.index(anchor) + 1
        ordered = [*remaining[:index], *PROVENANCE_FIELDS, *remaining[index:]]
        self.order_fields(ordered)

    def clean(self) -> dict[str, object]:
        """Require an AI extent, a picture choice, and a description when needed."""
        cleaned = super().clean()
        if self.reviewer is None:
            self.add_error(None, "A signed-in editor is required to record AI provenance.")
        ai_generated = bool(cleaned.get("ai_generated"))
        extent = cleaned.get("ai_extent")
        if ai_generated and extent not in {
            GenerationStatus.FULLY_AI,
            GenerationStatus.PARTIALLY_AI,
        }:
            self.add_error(
                "ai_extent",
                "Choose whether the image is fully AI-generated or partially AI-modified.",
            )
        elif not ai_generated:
            cleaned["ai_extent"] = ""
        description = (cleaned.get("description") or "").strip()
        needs_description = (
            ai_generated
            and extent in {GenerationStatus.FULLY_AI, GenerationStatus.PARTIALLY_AI}
            and cleaned.get("picture_like") == PictureLike.YES
        )
        if needs_description and not description:
            self.add_error(
                "description",
                "Describe what the image shows. This text is used as the accessible description.",
            )
        if self._requires_label(cleaned) and not self.errors:
            message = self._unlabelable_message(cleaned)
            if message:
                self._add_file_error(message)
        return cleaned

    def save(self, commit: bool = True) -> Model:
        """Save the image, record the decision, and embed the icon when required."""
        if commit:
            if not self.is_valid():
                raise ValueError(
                    "The image could not be saved because the data didn't validate."
                )
            self._raise_if_unlabelable()
            created = self.instance.pk is None
            image = super().save(commit=True)
            self._label_saved_image(image, created=created)
            return image

        image = super().save(commit=False)
        original_save: Callable[..., Model | None] = image.save
        created = image.pk is None

        def save_then_label(*args, **kwargs) -> Model | None:
            saved = original_save(*args, **kwargs)
            image.save = original_save
            self._label_saved_image(image, created=created)
            return saved

        image.save = save_then_label
        return image

    def _requires_label(self, cleaned: dict[str, object]) -> bool:
        """Return whether this submission must embed an icon.

        Args:
            cleaned: Cleaned form data.

        Returns:
            True when the editor confirmed a picture-like AI image.
        """
        return (
            bool(cleaned.get("ai_generated"))
            and cleaned.get("ai_extent")
            in {GenerationStatus.FULLY_AI, GenerationStatus.PARTIALLY_AI}
            and cleaned.get("picture_like") == PictureLike.YES
        )

    def _bytes_to_check(self, cleaned: dict[str, object]) -> bytes | None:
        """Return the file bytes this save would label.

        Args:
            cleaned: Cleaned form data.

        Returns:
            Uploaded or existing file bytes, or None when no file is available yet.
        """
        uploaded = cleaned.get("file")
        if hasattr(uploaded, "read"):
            position = uploaded.tell()
            uploaded.seek(0)
            data = uploaded.read()
            uploaded.seek(position)
            return data
        image_file = getattr(self.instance, "file", None)
        if not getattr(image_file, "name", ""):
            return None
        with image_file.open("rb") as handle:
            return handle.read()

    def _unlabelable_message(self, cleaned: dict[str, object]) -> str:
        """Return an editor-facing error when the file cannot take an icon.

        Args:
            cleaned: Cleaned form data.

        Returns:
            The error message, or an empty string when the file can be labelled.
        """
        data = self._bytes_to_check(cleaned)
        if data is None:
            return ""
        try:
            ensure_image_can_be_labelled(data, str(cleaned.get("ai_extent")))
        except AIImageLabellingError as exc:
            return f"The EU icon could not be embedded: {exc}"
        except PILImage.UnidentifiedImageError:
            return "The EU icon could not be embedded: the file is not a readable image."
        return ""

    def _add_file_error(self, message: str) -> None:
        """Attach a labelling error to the file field, or the form when it has none.

        Args:
            message: Editor-facing error.
        """
        if "file" in self.fields:
            self.add_error("file", message)
            return
        self.add_error(None, message)

    def _raise_if_unlabelable(self) -> None:
        """Stop a save that clean() could not check, such as the multiple uploader.

        Raises:
            ValidationError: The file cannot take an icon. No image row is written.
        """
        if not self._requires_label(self.cleaned_data):
            return
        message = self._unlabelable_message(self.cleaned_data)
        if not message:
            return
        self._discard_unsaved_file()
        raise forms.ValidationError(message)

    def _discard_unsaved_file(self) -> None:
        """Remove a file written before validation when the image row does not exist."""
        if self.instance.pk:
            return
        image_file = getattr(self.instance, "file", None)
        if not getattr(image_file, "name", ""):
            return
        try:
            path = Path(image_file.path)
        except NotImplementedError, ValueError, OSError:
            return
        if path.is_file():
            path.unlink()

    def _label_saved_image(self, image: Model, *, created: bool) -> None:
        """Store the disclosure and embed the icon in one transaction.

        Args:
            image: Image row that has just been saved.
            created: Whether this save inserted the image row.

        Raises:
            ValidationError: Labelling failed. A new image is deleted. An existing
            image keeps its previous disclosure.
        """
        try:
            with transaction.atomic():
                self._save_disclosure(image)
                label_image(image)
        except AIImageLabellingError as exc:
            image.__dict__.pop("ai_disclosure", None)
            if created:
                self._delete_image_and_file(image)
            raise forms.ValidationError(f"The EU icon could not be embedded: {exc}") from exc
        image.__dict__.pop("ai_disclosure", None)

    def _delete_image_and_file(self, image: Model) -> None:
        """Delete an image row and its public file after a failed label.

        Args:
            image: Image created by this save.
        """
        model = type(image)
        if model.objects.filter(pk=image.pk).exists():
            image.delete()
        self._unlink(image)

    def _unlink(self, image: Model) -> None:
        """Remove the public file if it is still on disk.

        Args:
            image: Image whose file should be removed.
        """
        image_file = getattr(image, "file", None)
        if not getattr(image_file, "name", ""):
            return
        try:
            path = Path(image_file.path)
        except NotImplementedError, ValueError, OSError:
            return
        if path.is_file():
            path.unlink()

    def _save_disclosure(self, image: Model) -> None:
        """Create or update the disclosure without changing label bookkeeping."""
        status = (
            self.cleaned_data["ai_extent"]
            if self.cleaned_data["ai_generated"]
            else GenerationStatus.NOT_AI
        )
        disclosure, _created = ImageAIDisclosure.objects.get_or_create(image=image)
        disclosure.generation_status = status
        disclosure.picture_like = self.cleaned_data["picture_like"]
        disclosure.reviewed_by = self.reviewer
        disclosure.reviewed_at = timezone.now()
        disclosure.save(
            update_fields=[
                "generation_status",
                "picture_like",
                "reviewed_by",
                "reviewed_at",
            ]
        )
