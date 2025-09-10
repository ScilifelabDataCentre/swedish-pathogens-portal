from django.urls import path
from .views import DataManagement 

urlpatterns = [
    path("", DataManagement.as_view(), name="data_management"),
]
