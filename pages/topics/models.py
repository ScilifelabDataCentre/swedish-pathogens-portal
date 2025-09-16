from django.db import models
from django.utils.text import slugify
from django.utils.safestring import mark_safe
import markdown


class Topic(models.Model):
    """Topic model for categorizing portal content.

    Represents topics that can be associated with dashboards,
    data highlights, and other portal content. Each topic has a name,
    description, content, and thumbnail image.

    Attributes:
        name (str): Display name of the topic (max 100 chars, unique).
        slug (str): URL-friendly version of name (auto-generated).
        description (str): Brief description for topic cards.
        content (str): Rich markdown content for detail pages.
        thumbnail_image (ImageField): Thumbnail image for topic cards.
        alert_message (str, optional): Prominent alert message for topic page.
        is_active (bool): Whether topic is visible (default: True).
        created_at (datetime): When topic was created.
        updated_at (datetime): When topic was last updated.

    Example:
        Create a new topic:

        .. code-block:: python

            topic = Topic.objects.create(
                name="COVID-19 Research",
                description="Research related to COVID-19",
                content="# COVID-19\n\nResearch content...",
                thumbnail_image="covid19.jpg"
            )
            # slug automatically generated as "covid-19-research"
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Name of the topic",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL-friendly version of the name (auto-generated from name)",
    )
    description = models.TextField(
        help_text="Description of the topic to display in the card"
    )
    content = models.TextField(
        help_text="Rich text content in markdown format (displayed on topic detail page)"
    )
    thumbnail_image = models.ImageField(
        upload_to="topics/images/",
        help_text="Thumbnail image for the topic card display",
    )
    alert_message = models.TextField(
        blank=True,
        null=True,
        help_text="Optional alert message to display prominently on the topic page",
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this topic is active and visible"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Topic"
        verbose_name_plural = "Topics"

    def __str__(self):
        """Return the topic name for string representation."""
        return self.name

    def save(self, *args, **kwargs):
        """Save the topic, auto-generating slug if not provided."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def display_image(self):
        """Return the URL of the thumbnail image."""
        return self.thumbnail_image.url

    @property
    def rendered_content(self):
        """Return content rendered as HTML from markdown."""
        return mark_safe(
            markdown.markdown(self.content, extensions=["extra", "codehilite"])
        )
