from django.views.generic import TemplateView

# Create your views here.


class Privacy(TemplateView):
    template_name = "privacy/index.html"
    extra_context = {
        "title": "Privacy Policy"
    }
