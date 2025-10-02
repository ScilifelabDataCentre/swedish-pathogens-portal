from utils.views import BaseTemplateView

# Create your views here.


class About(BaseTemplateView):
    template_name = "about/index.html"
    title = "About"


class Partners(BaseTemplateView):
    template_name = "about/partners.html"
    title = "Partners"


class Funding(BaseTemplateView):
    template_name = "about/funders.html"
    title = "Funders"


class Nodes(BaseTemplateView):
    template_name = "about/nodes.html"
    title = "Pathogens Portal Nodes"
