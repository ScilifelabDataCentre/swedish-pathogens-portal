from utils.views import BaseTemplateView


class Dashboards(BaseTemplateView):
    template_name = "dashboards/index.html"
    title = "Dashboard passed"
