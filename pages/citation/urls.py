from django.urls import path
from .views import Citation

app_name = "citation"

urlpatterns = [
    path("", Citation.as_view(), name="index"),
]


