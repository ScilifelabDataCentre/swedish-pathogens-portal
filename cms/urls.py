"""CMS URL patterns for HTMX endpoints and other non-Wagtail views."""

from django.urls import path

from cms.views.data_table import table_partial
from cms.views.liver_resource import (
    download_template,
    export_genes,
    export_module_scores,
    load_example,
    recompute,
    upload_de,
)

app_name = "cms"

urlpatterns = [
    path(
        "table-content/<int:page_pk>/<str:table_id>/",
        table_partial,
        name="table_partial",
    ),
    path(
        "liver/upload/",
        upload_de,
        name="liver_upload",
    ),
    path(
        "liver/recompute/",
        recompute,
        name="liver_recompute",
    ),
    path(
        "liver/example/<slug:example_slug>/",
        load_example,
        name="liver_load_example",
    ),
    path(
        "liver/template/",
        download_template,
        name="liver_download_template",
    ),
    path(
        "liver/export/modules/",
        export_module_scores,
        name="liver_export_modules",
    ),
    path(
        "liver/export/genes/",
        export_genes,
        name="liver_export_genes",
    ),
]
