from django.shortcuts import render

# Create your views here.
from django.views.generic import TemplateView
from utils.views import BaseTemplateView

# Create your views here.

class About(BaseTemplateView):
    template_name = "about/index.html"
    title = "About"


class Partners(BaseTemplateView):
    template_name = "about/partners.html"
    title = "Partners"


class Funding(BaseTemplateView):
    template_name = "about/funding.html"
    title = "Funding Projects"


class Nodes(BaseTemplateView):
    template_name = "about/nodes.html"
    title = "Pathogens Portal Nodes"
