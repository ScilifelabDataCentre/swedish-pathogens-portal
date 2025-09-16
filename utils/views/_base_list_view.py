from django.views.generic import ListView


class BaseListView(ListView):
    """Base list view for displaying collections of active items.

    This class provides common functionality for listing model instances that
    have an `is_active` field. Used by apps with collections like topics,
    data-highlights, dashboards, etc.

    Attributes:
        title (str): Page title to add to context. Defaults to empty string.
        ordering (str): Field name to order results by. Optional.

    Example:
        For a Topic model:

        .. code-block:: python

            class TopicListView(BaseListView):
                model = Topic
                template_name = "topics/index.html"
                context_object_name = "topics"
                title = "Research Topics"
                ordering = "name"

        This automatically:
        - Filters to active items (is_active=True)
        - Orders by specified field
        - Adds title to context

    Note:
        Model must have `is_active` boolean field.
    """

    title = ""

    def get_queryset(self):
        """Return only active items ordered by specified field"""
        queryset = self.model.objects.filter(is_active=True)

        # Apply ordering if specified
        if self.ordering:
            queryset = queryset.order_by(self.ordering)

        return queryset

    def get_context_data(self, **kwargs):
        """Add title to context"""
        context = super().get_context_data(**kwargs)
        if self.title:
            context["title"] = self.title
        return context
