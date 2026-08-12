"""App configuration for the portal_data app."""

from django.apps import AppConfig


class PortalDataConfig(AppConfig):
    """Configure the portal data Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "portal_data"
    verbose_name = "Portal Data"
