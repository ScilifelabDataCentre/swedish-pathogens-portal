from django.urls import path
from .views import Privacy

urlpatterns = [
    path("", Privacy.as_view(), name="privacy"),
]
