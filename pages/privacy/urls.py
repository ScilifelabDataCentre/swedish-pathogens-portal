from django.urls import path
from .views import Privacy

app_name = "privacy"

urlpatterns = [
    path("", Privacy.as_view(), name="index"),
]
