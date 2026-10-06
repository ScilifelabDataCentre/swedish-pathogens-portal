"""Provenance records for AI-generated Wagtail images."""

from django.apps.registry import Apps
from django.conf import settings
from django.db import models
from wagtail.images import get_image_model_string


class GenerationStatus(models.TextChoices):
    """How an image was produced."""

    UNREVIEWED = "unreviewed", "Unreviewed"
    NOT_AI = "not_ai", "Not AI-generated"
    FULLY_AI = "fully_ai", "Fully AI-generated"
    PARTIALLY_AI = "partially_ai", "Partially AI-modified"


class PictureLike(models.TextChoices):
    """Whether an image could be interpreted as a picture."""

    UNREVIEWED = "unreviewed", "Unreviewed"
    YES = "yes", "Yes"
    NO = "no", "No"


class ImageAIDisclosure(models.Model):
    """Editor-owned provenance for one Wagtail image.

    The labelling service reads this row. It does not infer provenance from the
    file name, title, or pixels.
    """

    image = models.OneToOneField(
        get_image_model_string(),
        on_delete=models.CASCADE,
        related_name="ai_disclosure",
    )
    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.UNREVIEWED,
    )
    picture_like = models.CharField(
        max_length=20,
        choices=PictureLike.choices,
        default=PictureLike.UNREVIEWED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    label_version = models.CharField(max_length=64, blank=True)
    labelled_file_hash = models.CharField(max_length=64, blank=True)
    labelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Meta options for AI image disclosures."""

        verbose_name = "AI image disclosure"
        verbose_name_plural = "AI image disclosures"

    def __str__(self) -> str:
        """Return a short label for the admin and shell."""
        return f"AI disclosure for image {self.image_id}"

    @property
    def requires_label(self) -> bool:
        """Return whether policy says this picture-like AI image needs an icon."""
        return (
            self.generation_status
            in {
                GenerationStatus.FULLY_AI,
                GenerationStatus.PARTIALLY_AI,
            }
            and self.picture_like == PictureLike.YES
        )

    @property
    def is_reviewed(self) -> bool:
        """Return whether an editor has confirmed this disclosure."""
        return self.reviewed_by_id is not None and self.reviewed_at is not None

    @property
    def is_ready_to_label(self) -> bool:
        """Return whether a confirmed disclosure should be labelled."""
        return self.requires_label and self.is_reviewed


def backfill_image_disclosures(apps: Apps, schema_editor: object) -> None:
    """Create one unreviewed disclosure for every Wagtail image that lacks one.

    Args:
        apps: Historical app registry supplied by the migration.
        schema_editor: Unused migration argument.
    """
    del schema_editor
    image_model = apps.get_model("wagtailimages", "Image")
    disclosure_model = apps.get_model("cms", "ImageAIDisclosure")
    existing_ids = set(disclosure_model.objects.values_list("image_id", flat=True))
    rows = [
        disclosure_model(
            image_id=image_id,
            generation_status=GenerationStatus.UNREVIEWED,
            picture_like=PictureLike.UNREVIEWED,
        )
        for image_id in image_model.objects.values_list("id", flat=True)
        if image_id not in existing_ids
    ]
    disclosure_model.objects.bulk_create(rows)
