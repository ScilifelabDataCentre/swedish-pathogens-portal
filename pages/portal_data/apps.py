"""App configuration for the portal_data app."""

from django.apps import AppConfig


class PortalDataConfig(AppConfig):
    """Configuration for the portal_data application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "pages.portal_data"
    verbose_name = "Portal Data"
