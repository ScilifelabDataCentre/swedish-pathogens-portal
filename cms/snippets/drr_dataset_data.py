"""Precomputed data snippet for DRR dataset pages."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.models import RevisionMixin
from wagtail.snippets.models import register_snippet


@register_snippet
class DrrDatasetData(RevisionMixin, models.Model):
    """Precomputed figures and summary statistics for one DRR dataset page.

    One row per dataset (``dataset_slug`` is unique and must match the
    ``DrrDatasetPage`` slug). Populated by the ``drr_precompute`` management
    command (FREYA-2556), not edited by hand. Duck-types the read interface
    ``DashboardPage`` and ``PlotlyFigureBlock`` expect (``data``,
    ``data_updated_at``, ``source_file_hash``).

    Deliberately separate from :class:`~cms.snippets.dashboard_data.DashboardData`
    rather than reusing it: DRR's write path cannot run through the admin upload
    hook and ``dashboard_visualisation.registry``. Precompute takes three inputs
    (feature table, CBCS metadata, optional UMAP coordinates) where the registry
    passes one; the feature tables can be >200 MB, past what parsing plus PCA
    can do inside an admin POST; and the command must also write the download
    artefacts under ``media/drr/<slug>/``, which the registry contract does not
    cover. The read side is identical on purpose so the inherited render path
    works unchanged.

    Attributes:
        dataset_title: Human-readable label for admin display.
        dataset_slug: Unique identifier matching the DrrDatasetPage slug.
        data: Pre-computed Plotly figure JSON keyed by figure_id.
        summary: Summary-statistics panel payload.
        source_file_hash: Combined SHA-256 over every precompute input (feature table,
            metadata, optional UMAP coordinates), so any input change busts the figure
            render cache. ``summary.source.sha256`` keeps the feature-table digest alone.
        data_updated_at: Public-facing date the underlying data was last updated.
        generated_at: Timestamp of the last precompute run.
    """

    dataset_title = models.CharField(max_length=255, default="")
    dataset_slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="Must match the DrrDatasetPage slug. One data row per dataset.",
    )
    data = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    source_file_hash = models.CharField(max_length=64, blank=True, editable=False)
    data_updated_at = models.DateField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    revisions = GenericRelation("wagtailcore.Revision", related_query_name="drrdatasetdata")

    panels = [
        MultiFieldPanel(
            [FieldPanel("dataset_title"), FieldPanel("dataset_slug")],
            heading="Dataset",
        ),
        FieldPanel("data_updated_at"),
        FieldPanel("data"),
        FieldPanel("summary"),
    ]

    class Meta:
        """Settings for the DrrDatasetData model."""

        ordering = ["dataset_slug"]
        verbose_name = "DRR dataset data"
        verbose_name_plural = "DRR dataset data"

    def __str__(self) -> str:
        """Return the admin display label for this row."""
        return self.dataset_title or self.dataset_slug

    @classmethod
    def get_data(cls, dataset_slug: str) -> DrrDatasetData | None:
        """Return the data row for a dataset slug, or None if absent."""
        try:
            return cls.objects.get(dataset_slug=dataset_slug)
        except cls.DoesNotExist:
            return None
