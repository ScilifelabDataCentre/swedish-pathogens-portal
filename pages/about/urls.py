from django.urls import path
from .views import About, Partners, Funding, Nodes

app_name = "about"

urlpatterns = [
    path("", About.as_view(), name="index"),
    path("partners/", Partners.as_view(), name="partners"),
    path("funders/", Funding.as_view(), name="funders"),
    path("pathogens-portal-nodes/", Nodes.as_view(), name="nodes"),
]
