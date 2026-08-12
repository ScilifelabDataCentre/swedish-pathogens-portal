"""Models for portal data."""

from __future__ import annotations

from django.db import models


class PortalDatasetIndex(models.Model):
    """Searchable index entry for one portal data bundle manifest."""

    class IngestionStatus(models.TextChoices):
        """Possible ingestion states for an indexed dataset."""

        IN_SYNC = "in_sync", "In sync"
        INVALID = "invalid", "Invalid"
        OUT_OF_SYNC = "out_of_sync", "Out of sync"
        HIDDEN = "hidden", "Hidden"
        WITHDRAWN = "withdrawn", "Withdrawn"

    dataset_id = models.CharField(max_length=255, unique=True)
    datatype = models.CharField(max_length=64, db_index=True)
    repository = models.CharField(max_length=128, default="spp-unit-bundles")
    unit = models.CharField(max_length=255, blank=True)

    bucket = models.CharField(max_length=255)
    manifest_key = models.TextField()
    dataset_prefix = models.TextField()

    title = models.TextField()
    year = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    files = models.JSONField(default=list)

    ingestion_status = models.CharField(
        max_length=32,
        choices=IngestionStatus.choices,
        default=IngestionStatus.INVALID,
        db_index=True,
    )
    validation_errors = models.JSONField(default=list, blank=True)

    public = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    withdrawn = models.BooleanField(default=False)

    indexed_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model metadata for portal dataset index entries."""

        indexes = [
            models.Index(fields=["datatype", "ingestion_status"]),
            models.Index(fields=["repository"]),
            models.Index(fields=["unit"]),
            models.Index(fields=["year"]),
        ]

    def __str__(self) -> str:
        """Return the dataset identifier."""
        return self.dataset_id
