"""Wagtail settings for the public EBI catalogue JSON envelope."""

from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.settings.models import BaseGenericSetting, register_setting

DEFAULT_CATALOGUE_NAME = "Swedish Pathogens Portal"
DEFAULT_RELEASE = "v2.6.16"
DEFAULT_RELEASE_DATE = "2026-08-28"


@register_setting
class EbiIndexSettings(BaseGenericSetting):
    """Envelope values for `/ebi-index.json` (name, release, optional GitHub URL).

    `entry_count` and `entries` are not stored here; the builder computes them.
    """

    name = models.CharField(
        max_length=255,
        default=DEFAULT_CATALOGUE_NAME,
        help_text="Catalogue name in the JSON envelope. Do not use the site name (dev suffix).",
    )
    release = models.CharField(
        max_length=64,
        default=DEFAULT_RELEASE,
        help_text="Used when the GitHub latest-release URL is empty or the fetch fails.",
    )
    release_date = models.CharField(
        max_length=10,
        default=DEFAULT_RELEASE_DATE,
        help_text="YYYY-MM-DD. Same fallback as release.",
    )
    github_releases_latest_url = models.URLField(
        blank=True,
        help_text=(
            "Optional GitHub API URL: https://api.github.com/repos/{owner}/{repo}/releases/latest"
        ),
    )

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("name"),
                FieldPanel("release"),
                FieldPanel("release_date"),
                FieldPanel("github_releases_latest_url"),
            ],
            heading="EBI index",
        ),
    ]

    class Meta:
        """Meta options for EBI index settings."""

        verbose_name = "EBI index"
