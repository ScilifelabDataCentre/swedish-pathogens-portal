from utils.views import BaseListView, BaseDetailView
from .models import Topic


class TopicListView(BaseListView):
    """Display a list of all active topics"""

    model = Topic
    template_name = "topics/index.html"
    context_object_name = "topics"
    title = "Topics"
    ordering = "name"  # Topics are sorted alphabetically by name


class TopicDetailView(BaseDetailView):
    """Display detailed information about a specific topic"""

    model = Topic
    template_name = "topics/topic_detail.html"
    context_object_name = "topic"
