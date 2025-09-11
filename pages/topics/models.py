from django.db import models
from django.utils.text import slugify
from django.utils.safestring import mark_safe
import markdown


class Topic(models.Model):
    """Topic model"""

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
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def display_image(self):
        """Return thumbnail image URL if available, otherwise return default placeholder"""
        if self.thumbnail_image:
            return self.thumbnail_image.url
        return "/static/images/topic-placeholder.svg"

    @property
    def rendered_content(self):
        """Return content rendered as HTML from markdown"""
        if self.content:
            return mark_safe(
                markdown.markdown(self.content, extensions=["extra", "codehilite"])
            )
        return ""
