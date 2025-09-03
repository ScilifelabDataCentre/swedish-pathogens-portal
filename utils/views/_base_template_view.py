from django.views.generic import TemplateView


class BaseTemplateView(TemplateView):
    """Inherits Django TemplateView class and adds title to the context if exists"""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = getattr(self, "title", "")
        return context
