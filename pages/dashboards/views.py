from utils.views import BaseTemplateView


class DashboardsIndex(BaseTemplateView):
    """Index page for Dashboard

    WIP: currently a simple templateview but will be updated later
    """

    template_name = "dashboards/index.html"
    title = "Data dashboards"
