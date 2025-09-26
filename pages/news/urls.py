from django.urls import path
from .views import NewsListView, NewsDetailView

app_name = 'news'

urlpatterns = [
    path('', NewsListView.as_view(), name='index'),
    path('<slug:slug>/', NewsDetailView.as_view(), name='detail'),
]
