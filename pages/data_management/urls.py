from django.urls import path
from .views import DataManagement 

app_name = "data_management"

urlpatterns = [
    path("", DataManagement.as_view(), name="index"),
]
