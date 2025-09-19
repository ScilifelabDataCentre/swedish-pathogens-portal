from django.views.generic import TemplateView


class BaseTemplateView(TemplateView):
    """Base template view for static pages.

    This class can be inherited by static page view classes that only
    render a template by passing a context. The defined attributes
    can be set in child classes to be added to the context.

    Attributes:
        title (str): Page title to add to context. Optional.
        description (str): Meta description to add to context. Optional.
        extra_context (dict): Additional context data. Optional.

    Example:
        For a static about page:

        .. code-block:: python

            class AboutView(BaseTemplateView):
                template_name = "about/index.html"
                title = "About Us"
                description = "Learn about our organization"
                extra_context = {"show_contact": True}
    """

    title = ""
    description = ""
    extra_context = None
    breadcrumbs = None

    def get_context_data(self, **kwargs):
        """Add title, description, and extra_context to template context."""
        context = super().get_context_data(**kwargs)

        if self.title:
            context["title"] = self.title

        if self.description:
            context["description"] = self.description

        if self.breadcrumbs is not None:
            context["breadcrumbs"] = self.breadcrumbs

        if self.extra_context is not None and isinstance(self.extra_context, dict):
            context.update(self.extra_context)

        return context
