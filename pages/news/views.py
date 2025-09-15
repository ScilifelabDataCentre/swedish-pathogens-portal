from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.views.generic import ListView, DetailView
from .models import News


class NewsListView(ListView):
    model = News
    template_name = 'news/list.html'
    context_object_name = 'news_list'
    paginate_by = 10
    
    def get_queryset(self):
        return News.objects.filter(published=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'News | Swedish Pathogens Portal'
        context['breadcrumbs'] = [
            {"title": "Home", "url": "/"},
            {"title": "News", "url": None}
        ]
        return context


class NewsDetailView(DetailView):
    model = News
    template_name = 'news/detail.html'
    context_object_name = 'news'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        return News.objects.filter(published=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        news = self.get_object()
        context['title'] = f'{news.title} | Swedish Pathogens Portal'
        context['breadcrumbs'] = [
            {"title": "Home", "url": "/"},
            {"title": "News", "url": "/news/"},
            {"title": news.title, "url": None}
        ]
        return context
