"""Wagtail CMS Page models."""

from .basic_page import BasicPage
from .catalogue import CataloguePage
from .dashboard import DashboardPage, DashboardTopic
from .dashboard_index import DashboardIndexPage
from .drr_dataset import DrrDatasetPage
from .highlights_and_editorials import (
    HighlightsAndEditorialsPage,
    HighlightsAndEditorialsTopic,
)
from .highlights_and_editorials_index import HighlightsAndEditorialsIndexPage
from .home import HomePage
from .news import NewsPage
from .news_index import NewsIndexPage
from .outbreaks import OutbreakPage
from .outbreaks_index import OutbreaksIndexPage
from .plp_index import PlpIndexPage
from .plp_project import PlpProjectPage
from .portal_data import PortalDataPage
from .topics import TopicPage
from .topics_index import TopicsIndexPage

__all__ = [
    "BasicPage",
    "CataloguePage",
    "DashboardIndexPage",
    "DashboardPage",
    "DashboardTopic",
    "DrrDatasetPage",
    "HighlightsAndEditorialsIndexPage",
    "HighlightsAndEditorialsPage",
    "HighlightsAndEditorialsTopic",
    "HomePage",
    "NewsIndexPage",
    "NewsPage",
    "OutbreakPage",
    "OutbreaksIndexPage",
    "PlpIndexPage",
    "PlpProjectPage",
    "PortalDataPage",
    "TopicPage",
    "TopicsIndexPage",
]
