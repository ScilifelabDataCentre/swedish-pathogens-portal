from django.urls import path
from .views import DashboardsIndex

app_name = "dashboards"

urlpatterns = [
    path("", DashboardsIndex.as_view(), name="index"),
]
