from django.urls import path
from .views import TopicListView, TopicDetailView

app_name = "topics"

urlpatterns = [
    path("", TopicListView.as_view(), name="index"),
    path("<slug:slug>/", TopicDetailView.as_view(), name="topic_detail"),
]
