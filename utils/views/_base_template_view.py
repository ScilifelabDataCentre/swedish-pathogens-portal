from django.views.generic import TemplateView


class BaseTemplateView(TemplateView):
    """Base template view class

    This class can be inherited by satic page view classes that only
    renders a template by passing a context. Below defined attributes
    can be set in the child classes to be added to the context.
    """

    title = ""
    description = ""
    extra_context = None
    breadcrumbs = None

    def get_context_data(self, **kwargs):
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
