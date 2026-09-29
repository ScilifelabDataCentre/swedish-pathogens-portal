"""Wagtail image form that records AI provenance."""

from collections.abc import Callable

from django import forms
from django.db.models import Model
from django.utils import timezone
from wagtail.images.forms import BaseImageForm

from cms.image_ai import GenerationStatus, ImageAIDisclosure, PictureLike

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

    Saving records the signed-in editor as the reviewer. This form does not
    embed an icon or rewrite the image file.
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
        return cleaned

    def save(self, commit: bool = True) -> Model:
        """Save the image, then record the editor's confirmed provenance."""
        image = super().save(commit=commit)
        if commit:
            self._save_disclosure(image)
            return image

        original_save: Callable[..., Model | None] = image.save

        def save_then_record_disclosure(*args, **kwargs) -> Model | None:
            saved = original_save(*args, **kwargs)
            image.save = original_save
            self._save_disclosure(image)
            return saved

        image.save = save_then_record_disclosure
        return image

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
