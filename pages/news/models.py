from django.db import models
from django.utils import timezone
from django.urls import reverse


class News(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, help_text="URL-friendly version of the title")
    image = models.ImageField(upload_to='news/images/', blank=True, null=True)
    content = models.TextField()
    excerpt = models.TextField(max_length=500, blank=True, help_text="Short summary for news listings")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    published = models.BooleanField(default=True)
    featured = models.BooleanField(default=False, help_text="Show this news item prominently")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "News Article"
        verbose_name_plural = "News Articles"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('news:detail', kwargs={'slug': self.slug})
