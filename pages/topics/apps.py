from django.apps import AppConfig


class TopicsConfig(AppConfig):
    """Configuration for the topics app.

    Manages the topics application which handles topics
    categorization and content management for the portal.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "pages.topics"
