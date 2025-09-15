from django.shortcuts import render

# Create your views here.
from django.views.generic import TemplateView
from utils.views import BaseTemplateView

# Create your views here.

class About(BaseTemplateView):
    template_name = "about/index.html"
    title = "About | Swedish Pathogens Portal"


class Partners(BaseTemplateView):
    template_name = "about/partners.html"
    title = "Partners | Swedish Pathogens Portal"


class Funding(BaseTemplateView):
    template_name = "about/funding.html"
    title = "Funding Projects | Swedish Pathogens Portal"


class Nodes(BaseTemplateView):
    template_name = "about/nodes.html"
    title = "Pathogens Portal Nodes | Swedish Pathogens Portal"
