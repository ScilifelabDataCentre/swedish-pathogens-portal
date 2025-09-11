from django.views.generic import ListView


class BaseListView(ListView):
    """Base list view class for active items

    This class provides common functionality for listing active items
    across all apps. Child classes can override title and ordering.
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
