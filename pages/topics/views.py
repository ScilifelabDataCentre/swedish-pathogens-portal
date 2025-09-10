from django.views.generic import ListView, DetailView
from .models import Topic


class TopicListView(ListView):
    """Display a list of all active topics"""
    model = Topic
    template_name = "topics/topic_list.html"
    context_object_name = "topics"
    
    def get_queryset(self):
        """Return only active topics ordered by name"""
        return Topic.objects.filter(is_active=True).order_by("name")
    
    def get_context_data(self, **kwargs):
        """Add additional context data"""
        context = super().get_context_data(**kwargs)
        context["title"] = "Topics"
        return context


class TopicDetailView(DetailView):
    """Display detailed information about a specific topic"""
    model = Topic
    template_name = "topics/topic_detail.html"
    context_object_name = "topic"
    slug_field = "slug"
    slug_url_kwarg = "slug"
    
    def get_queryset(self):
        """Return only active topics"""
        return Topic.objects.filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        """Add additional context data"""
        context = super().get_context_data(**kwargs)
        context["title"] = self.object.name
        return context
