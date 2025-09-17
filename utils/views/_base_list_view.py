from django.views.generic import ListView


class BaseListView(ListView):
    """Base list view for displaying collections of filtered items.

    This class provides common functionality for listing model instances with
    flexible filtering capabilities. Used by apps with collections like topics,
    data-highlights, dashboards, etc.

    Attributes:
        title (str): Page title to add to context. Defaults to empty string.
        ordering (str): Field name to order results by. Optional.
        extra_context (dict): Additional context data. Optional.
        filter_* (any): Custom filter attributes. Any attribute starting with
            'filter_' will be used as a filter condition.

    Example:
        For a Topic model:

        .. code-block:: python

            class TopicListView(BaseListView):
                model = Topic
                template_name = "topics/index.html"
                context_object_name = "topics"
                title = "Research Topics"
                ordering = "name"
                extra_context = {"show_filters": True, "page_size": 20}

        For custom filtering:

        .. code-block:: python

            class PublishedTopicsView(BaseListView):
                model = Topic
                filter_status = "published"
                filter_category = "research"
                ordering = "created_at"

        This automatically:
        - Filters using custom filter_* attributes or defaults to is_active=True
        - Orders by specified field
        - Adds title to context
        - Merges extra_context into context

    Note:
        Model must have `is_active` boolean field for default filtering.
    """

    title = ""

    def get_queryset(self):
        """Return filtered items ordered by specified field"""
        # Get custom filter arguments from class attributes
        filter_args = {
            k.replace("filter_", ""): v
            for k, v in vars(self).items()
            if k.startswith("filter_")
        }

        # Use custom filters or default to is_active
        queryset = self.model.objects.filter(is_active=True, **filter_args)

        # Apply ordering if specified
        if self.ordering:
            queryset = queryset.order_by(self.ordering)

        return queryset

    def get_context_data(self, **kwargs):
        """Add title and extra_context to context"""
        context = super().get_context_data(**kwargs)
        if self.title:
            context["title"] = self.title

        # Add extra_context if defined
        if hasattr(self, "extra_context") and self.extra_context:
            context.update(self.extra_context)

        return context
