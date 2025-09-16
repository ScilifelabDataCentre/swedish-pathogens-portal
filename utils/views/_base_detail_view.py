from django.views.generic import DetailView


class BaseDetailView(DetailView):
    """Base detail view for displaying individual active items.

    This class provides common functionality for displaying individual model
    instances that have an `is_active` field. Used by apps with collections
    like topics, data-highlights, dashboards, etc.

    Attributes:
        slug_field (str): Model field for URL lookups. Defaults to "slug".
        slug_url_kwarg (str): URL keyword argument name. Defaults to "slug".

    Example:
        For a Topic model:

        .. code-block:: python

            class TopicDetailView(BaseDetailView):
                model = Topic
                template_name = "topics/topic_detail.html"
                context_object_name = "topic"

        This automatically:
        - Filters to active items (is_active=True)
        - Uses 'slug' field for URL lookups
        - Adds object.name as 'title' in context

    Note:
        Model must have `is_active` boolean field and `name` field.
    """

    # Explicit default values for clarity and consistency
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        """Return only active items"""
        return self.model.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        """Add title to context"""
        context = super().get_context_data(**kwargs)
        context["title"] = self.object.name
        return context
