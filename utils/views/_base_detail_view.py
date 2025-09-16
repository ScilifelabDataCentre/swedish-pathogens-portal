from django.views.generic import DetailView


class BaseDetailView(DetailView):
    """Base detail view for displaying individual filtered items.

    This class provides common functionality for displaying individual model
    instances with flexible filtering capabilities. Used by apps with collections
    like topics, data-highlights, dashboards, etc.

    Attributes:
        title (str): Page title. If empty, uses object's string representation.
        slug_field (str): Model field for URL lookups. Defaults to "slug".
        slug_url_kwarg (str): URL keyword argument name. Defaults to "slug".
        extra_context (dict): Additional context data. Optional.
        filter_* (any): Custom filter attributes. Any attribute starting with
            'filter_' will be used as a filter condition.

    Example:
        For a Topic model:

        .. code-block:: python

            class TopicDetailView(BaseDetailView):
                model = Topic
                template_name = "topics/topic_detail.html"
                context_object_name = "topic"
                title = "Topic Details"  # Custom title
                extra_context = {"show_related": True}

        For custom filtering:

        .. code-block:: python

            class PublishedTopicDetailView(BaseDetailView):
                model = Topic
                filter_status = "published"
                filter_category = "research"

        This automatically:
        - Filters using custom filter_* attributes or defaults to is_active=True
        - Uses 'slug' field for URL lookups
        - Adds title to context (custom or object.__str__)
        - Merges extra_context into context

    Note:
        Model must have `is_active` boolean field for default filtering and
        implement `__str__` method.
    """

    # Explicit default values for clarity and consistency
    title = ""
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        """Return filtered items"""
        # Get custom filter arguments from class attributes
        filter_args = {
            k.replace("filter_", ""): v
            for k, v in vars(self).items()
            if k.startswith("filter_")
        }

        # Use custom filters or default to is_active
        if filter_args:
            return self.model.objects.filter(**filter_args)
        else:
            return self.model.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        """Add title and extra_context to context"""
        context = super().get_context_data(**kwargs)
        context["title"] = self.title or str(self.object)

        # Add extra_context if defined
        if hasattr(self, "extra_context") and self.extra_context:
            context.update(self.extra_context)

        return context
