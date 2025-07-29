from django.views.generic import TemplateView

# Create your views here.

class Home(TemplateView):
    template_name = "home/index.html"
    extra_context = {
        "title": "Swedish Pathogens Portal: supporting pandemic preparedness"
    }
