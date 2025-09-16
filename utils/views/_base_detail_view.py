from django.views.generic import DetailView


class BaseDetailView(DetailView):
    """Base detail view for displaying individual active items.

    This class provides common functionality for displaying individual model
    instances that have an `is_active` field. Used by apps with collections
    like topics, data-highlights, dashboards, etc.

    Attributes:
        title (str): Page title. If empty, uses object's string representation.
        slug_field (str): Model field for URL lookups. Defaults to "slug".
        slug_url_kwarg (str): URL keyword argument name. Defaults to "slug".
        extra_context (dict): Additional context data. Optional.

    Example:
        For a Topic model:

        .. code-block:: python

            class TopicDetailView(BaseDetailView):
                model = Topic
                template_name = "topics/topic_detail.html"
                context_object_name = "topic"
                title = "Topic Details"  # Custom title
                extra_context = {"show_related": True}

        This automatically:
        - Filters to active items (is_active=True)
        - Uses 'slug' field for URL lookups
        - Adds title to context (custom or object.__str__)
        - Merges extra_context into context

    Note:
        Model must have `is_active` boolean field and implement `__str__` method.
    """

    # Explicit default values for clarity and consistency
    title = ""
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        """Return only active items"""
        return self.model.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        """Add title and extra_context to context"""
        context = super().get_context_data(**kwargs)
        context["title"] = self.title or str(self.object)

        # Add extra_context if defined
        if hasattr(self, "extra_context") and self.extra_context:
            context.update(self.extra_context)

        return context
