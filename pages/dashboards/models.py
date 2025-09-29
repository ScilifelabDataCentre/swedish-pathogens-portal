from django.db import models


class DashboardData(models.Model):
    """Dashboards model for visualisation data

    WIP - this is initial placehoder table for development,
    will be modified and finalised later based on the neccessity.
    The current purpose is to decouple the blob server dependency
    for the plot data for the dashboards, which will be saved in
    this table.

    Attributes:
        dashboard (str): Name of the dashboard the data relevant to.
        data_source (str): An optional URL string for the source data.
        data (json): Data needed for the corresponding dashboard (JSON format).
        created_at (datetime): When dashboard data was created.
        updated_at (datetime): When dashboard data was last updated.
    """

    dashboard = models.CharField(
        max_length=50,
        unique=True,
        help_text="Name of the Dashboard",
    )
    data_source = models.URLField(
        max_length=150, blank=True, help_text="Optional: URL of source raw data"
    )
    data = models.JSONField(help_text="Data related to the dashboard in JSON format")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dashboards Data"
        verbose_name_plural = "Dashboards Data"

    def __str__(self):
        """Return the dashboard name for string representation."""
        return self.dashboard
