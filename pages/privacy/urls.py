from django.urls import path
from .views import Privacy

urlpatterns = [
    path("privacy/", Privacy.as_view(), name="privacy"),
]
