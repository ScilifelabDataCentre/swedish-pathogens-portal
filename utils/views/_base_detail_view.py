from django.views.generic import DetailView


class BaseDetailView(DetailView):
    """Base detail view class for active items

    This class provides common functionality for displaying active items
    across all apps. Child classes can override title format.
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
