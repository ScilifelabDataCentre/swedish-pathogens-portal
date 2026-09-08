"""URL configuration for the portal data page."""

from django.urls import path

from .views import (
    BulkDownloadScript,
    DataTypeList,
    DownloadStudyFile,
    ExportSelected,
    StudyFiles,
)

app_name = "portal_data"

DEFAULT = {"datatype": "metabolomics"}

urlpatterns = [
    # Root listing page: /portal-data/
    path("", DataTypeList.as_view(), DEFAULT, name="index"),
    # Bulk export of the selected studies' metadata (TSV/JSON)
    path("export/", ExportSelected.as_view(), DEFAULT, name="data_export"),
    # Bulk download script for the selected studies' MetaboLights data
    path("download/", BulkDownloadScript.as_view(), DEFAULT, name="data_download"),
    # Per-study file browser (lists files under the study)
    path(
        "<slug:accession>/files/",
        StudyFiles.as_view(),
        DEFAULT,
        name="data_files",
    ),
    # Download an individual file from a study (relpath may contain slashes)
    path(
        "<slug:accession>/files/<path:relpath>/",
        DownloadStudyFile.as_view(),
        DEFAULT,
        name="data_file",
    ),
]
