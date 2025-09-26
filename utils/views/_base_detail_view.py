from django.views.generic import DetailView


class BaseDetailView(DetailView):
    """Base detail view for displaying individual active items with custom filtering.

    This class provides common functionality for displaying individual model
    instances that are always filtered by is_active=True and can have additional
    custom filters applied. Used by apps with collections like topics, data-highlights, dashboards, etc.

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
        - Filters by is_active=True and any custom filter_* attributes
        - Uses 'slug' field for URL lookups
        - Adds title to context (custom or object.__str__)
        - Merges extra_context into context

    Note:
        Model must have `is_active` boolean field and implement `__str__` method.
        All queries will filter by is_active=True and can have additional custom
        filters applied via filter_* attributes.
    """

    # Explicit default values for clarity and consistency
    title = ""
    slug_field = "slug"
    slug_url_kwarg = "slug"
    extra_context = None

    def get_queryset(self):
        """Return active items with custom filters applied"""
        # Get custom filter arguments from class attributes
        filter_args = {
            k.replace("filter_", ""): v
            for k, v in vars(self).items()
            if k.startswith("filter_")
        }

        # Always filter by is_active=True and apply any custom filters
        return self.model.objects.filter(is_active=True, **filter_args)

    def get_context_data(self, **kwargs):
        """Add title and extra_context to context"""
        context = super().get_context_data(**kwargs)
        context["title"] = self.title or str(self.object)

        # Add extra_context if defined
        if self.extra_context is not None and isinstance(self.extra_context, dict):
            context.update(self.extra_context)

        return context
