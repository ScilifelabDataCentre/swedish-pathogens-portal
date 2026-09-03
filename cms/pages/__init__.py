"""Wagtail CMS Page models."""

from .available_data import AvailableDataPage
from .basic_page import BasicPage
from .catalogue import CataloguePage
from .contact import ContactPage
from .dashboard import DashboardEbiPathogen, DashboardPage, DashboardTopic
from .dashboard_index import DashboardIndexPage
from .drr_dataset import DrrDatasetPage
from .highlights_and_editorials import (
    HighlightsAndEditorialsPage,
    HighlightsAndEditorialsTopic,
)
from .highlights_and_editorials_index import HighlightsAndEditorialsIndexPage
from .home import HomePage
from .liver_resource import LiverResourceDashboardPage
from .news import NewsPage
from .news_index import NewsIndexPage
from .outbreaks import OutbreakPage
from .outbreaks_index import OutbreaksIndexPage
from .plp_index import PlpIndexPage
from .plp_project import PlpProjectPage
from .portal_data import PortalDataPage
from .publications import PublicationsPage
from .slu_dashboard import SLUDashboardPage
from .slu_dashboard_subpage import SLUDashboardSubPage
from .topics import TopicPage
from .topics_index import TopicsIndexPage

__all__ = [
    "AvailableDataPage",
    "BasicPage",
    "CataloguePage",
    "ContactPage",
    "DashboardEbiPathogen",
    "DashboardIndexPage",
    "DashboardPage",
    "DashboardTopic",
    "DrrDatasetPage",
    "HighlightsAndEditorialsIndexPage",
    "HighlightsAndEditorialsPage",
    "HighlightsAndEditorialsTopic",
    "HomePage",
    "LiverResourceDashboardPage",
    "NewsIndexPage",
    "NewsPage",
    "OutbreakPage",
    "OutbreaksIndexPage",
    "PlpIndexPage",
    "PlpProjectPage",
    "PortalDataPage",
    "PublicationsPage",
    "SLUDashboardPage",
    "SLUDashboardSubPage",
    "TopicPage",
    "TopicsIndexPage",
]
