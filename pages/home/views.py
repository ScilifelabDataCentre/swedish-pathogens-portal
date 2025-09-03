from utils.views import BaseTemplateView


class Home(BaseTemplateView):
    template_name = "home/index.html"
    title = "Swedish Pathogens Portal: supporting pandemic preparedness"
