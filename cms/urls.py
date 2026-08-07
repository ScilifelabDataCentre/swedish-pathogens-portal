"""CMS URL patterns for HTMX endpoints and other non-Wagtail views."""

from django.urls import path

from cms.views.data_table import table_partial

app_name = "cms"

urlpatterns = [
    path(
        "table-content/<int:page_pk>/<str:table_id>/",
        table_partial,
        name="table_partial",
    ),
]
