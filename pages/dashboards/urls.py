from django.urls import path
from .views import Dashboards, SEECWastewater, SEECVirus, SEECMethodology

urlpatterns = [
    path("", Dashboards.as_view(), name="dashboards"),
    path("seec-wbs", SEECWastewater.as_view(), name="seec-wbs"),
    path("seec-wbs/methodology", SEECMethodology.as_view(), name="seec-methodology"),
    # Per-virus clean URLs using a single dashboard + permalinks
    path("seec-wbs/<slug:virus>", SEECVirus.as_view(), name="seec-virus"),
]
