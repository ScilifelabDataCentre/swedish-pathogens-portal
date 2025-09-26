from django.urls import path
from .views import About, Partners, Funding, Nodes

urlpatterns = [
    path("", About.as_view(), name="about"),
    path("partners/", Partners.as_view(), name="partners"),
    path("funders/", Funding.as_view(), name="funders"),
    path("pathogens-portal-nodes/", Nodes.as_view(), name="nodes"),
]
