"""CMS page for a single Drug Repurposing Resource (DRR) dataset."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import polars as pl
from django.db import models
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.routable_page.models import RoutablePageMixin, path

from cms.pages.dashboard import DashboardPage
from cms.services.file_downloads import serve_file_from_directory
from dashboard_visualisation.drr import artefact_dir

if TYPE_CHECKING:
    from pathlib import Path

    from cms.snippets.drr_dataset_data import DrrDatasetData

# Everything outside this set is dropped from a download's filename. Compound
# ids are not restricted to it — control placeholders such as ``[stau]`` are
# legitimate ``cbkid`` values — so this sanitises the header only.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

# The compound-index columns the picker labels from. ``name`` and ``kind`` are
# read when present rather than required: an index built without CBCS metadata
# carries neither, and the picker still has to offer every downloadable id.
_COMPOUND_OPTION_COLUMNS = ("cbkid", "name", "kind")


class DrrDatasetPage(RoutablePageMixin, DashboardPage):
    """A Drug Repurposing Resource dataset page (dataset-as-page).

    Lives under the existing Dashboards index and subclasses
    :class:`~cms.pages.dashboard.DashboardPage` to reuse its card fields,
    related topics, keywords, table of contents, and the server-side Plotly
    render path, while sourcing figures and summary statistics from
    :class:`~cms.snippets.drr_dataset_data.DrrDatasetData` instead of
    ``DashboardData``. ``RoutablePageMixin`` serves the per-dataset feature
    downloads and the raw-image 302 link-out (mvp-spec.md section 8); the
    imagery itself stays with the upstream study and is never hosted or proxied
    here.

    Attributes:
        organism: Source organism label (defaults to SARS-CoV-2).
        cell_line: Cell line used in the screen (e.g. A549-ACE2).
        screen_type: Screen description (e.g. Validation Cell Painting).
        upstream_accession: Upstream repository accession (e.g. S-BIAD2580).
        upstream_bia_url: Upstream raw-image study URL; target of the 302 link-out.
    """

    template = "cms/pages/drr_dataset.html"
    parent_page_types = ["cms.DashboardIndexPage"]
    subpage_types: list[str] = []

    organism = models.CharField(max_length=255, default="SARS-CoV-2")
    cell_line = models.CharField(max_length=255, blank=True)
    screen_type = models.CharField(max_length=255, blank=True)
    upstream_accession = models.CharField(max_length=64, blank=True)
    upstream_bia_url = models.URLField(blank=True)

    content_panels = [
        *DashboardPage.content_panels[:-1],
        MultiFieldPanel(
            [
                FieldPanel("organism"),
                FieldPanel("cell_line"),
                FieldPanel("screen_type"),
                FieldPanel("upstream_accession"),
                FieldPanel(
                    "upstream_bia_url",
                    help_text="Upstream raw-image study; target of the raw-image 302 link-out.",
                ),
            ],
            heading="Dataset metadata",
        ),
        DashboardPage.content_panels[-1],
    ]

    class Meta:
        """Meta options for the DrrDatasetPage model."""

        verbose_name = "DRR Dataset Page"

    @cached_property
    def dashboard_data(self) -> DrrDatasetData | None:
        """Return the DRR precomputed data row keyed by this page's slug."""
        from cms.snippets.drr_dataset_data import DrrDatasetData

        return DrrDatasetData.get_data(self.slug)

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the DRR summary payload, the download URLs and the compound picker."""
        context = super().get_context(request)
        context["summary"] = getattr(self.dashboard_data, "summary", {})

        download_urls = self._download_urls()
        if download_urls:
            context["download_urls"] = download_urls

        # The picker exists to submit to the per-compound slice, so it is
        # withheld unless that route can serve — otherwise every option 404s.
        if "compound_base" in download_urls:
            compounds = self._compound_options()
            if compounds:
                context["compounds"] = compounds

        return context

    # ------------------------------------------------------------------ #
    # Downloads (spec section 8)                                         #
    # ------------------------------------------------------------------ #

    def _artefact_dir(self) -> Path:
        """Return this dataset's derived-artefact directory."""
        return artefact_dir(self.slug)

    def _download_urls(self) -> dict[str, str]:
        """Map each available download to its URL.

        Artefact presence is checked on disk, so a page created before
        ``drr_precompute`` has run advertises nothing instead of linking to a
        404. The raw-image link-out follows the same rule against a different
        precondition: it is not an artefact, so it depends only on the editorial
        upstream URL.

        Returns:
            dict[str, str]: Template keys mapped to URLs, empty when nothing has
                been precomputed and no upstream study is configured.
        """
        page_url = self.url or ""
        artefacts = self._artefact_dir()

        urls = {
            key: page_url + self.reverse_subpage(route_name)
            for key, filename, route_name in (
                ("csv", "features.csv", "download_features_csv"),
                ("parquet", "features.parquet", "download_features_parquet"),
            )
            if (artefacts / filename).is_file()
        }

        # The per-compound slice filters the Parquet table, so it is offered
        # whenever that exists, and the compound picker submits to it.
        if (artefacts / "features.parquet").is_file():
            urls["compound_base"] = page_url + self.reverse_subpage("download_compound")

        # The link-out needs no precompute — imagery is never an artefact of
        # ours — so it is offered as soon as an upstream study is set, and
        # withheld rather than advertised as a 404 when it is not.
        if self.upstream_bia_url:
            urls["raw_images"] = page_url + self.reverse_subpage("raw_images")

        return urls

    def _compound_options(self) -> list[dict[str, str]]:
        """List every precomputed compound as an option for the picker.

        Reads ``compounds.parquet``, the index precompute builds by grouping the
        feature table, so the option set is exactly the set of ``cbkid`` values
        the per-compound slice can serve: no option 404s and no compound is
        hidden behind one. Nothing is dropped — the compounds the CBCS join left
        unannotated keep their bare id, and control placeholders keep theirs.

        Returns:
            list[dict[str, str]]: ``cbkid`` / ``label`` pairs, compounds before
                controls and then by label; empty when no index is precomputed.
        """
        index = self._artefact_dir() / "compounds.parquet"
        if not index.is_file():
            return []

        present = pl.scan_parquet(index).collect_schema().names()
        columns = [column for column in _COMPOUND_OPTION_COLUMNS if column in present]
        rows = pl.read_parquet(index, columns=columns).to_dicts()

        options = sorted(
            (
                (row.get("kind") == "control", self._compound_label(row), row["cbkid"])
                for row in rows
            ),
            key=lambda option: (option[0], option[1].casefold(), option[2]),
        )
        return [{"cbkid": cbkid, "label": label} for _, label, cbkid in options]

    @staticmethod
    def _compound_label(row: dict[str, Any]) -> str:
        """Return one compound's picker label.

        Args:
            row: A ``compounds.parquet`` row: ``cbkid``, plus ``name`` and
                ``kind`` when the index carries them.

        Returns:
            str: ``<name> (<cbkid>)`` once the CBCS join annotated the compound,
                ``<cbkid> (control)`` for a non-CBCS control id, and the bare
                ``cbkid`` for a compound the join did not annotate.
        """
        cbkid = row["cbkid"]
        if row.get("kind") == "control":
            return f"{cbkid} (control)"

        name = row.get("name")
        return f"{name} ({cbkid})" if name else cbkid

    def _serve_artefact(self, request: HttpRequest, filename: str) -> FileResponse:
        """Serve one derived artefact from this dataset's directory.

        Args:
            request: The incoming request (unused; kept for route symmetry).
            filename: Name of the artefact inside ``media/drr/<slug>/``.

        Returns:
            FileResponse: The artefact as an attachment.

        Raises:
            Http404: If the artefact is missing or the path escapes the directory.
        """
        return serve_file_from_directory(self._artefact_dir(), filename)

    @staticmethod
    def _attachment_filename(cbkid: str) -> str:
        """Return a header-safe filename for a per-compound download.

        Args:
            cbkid: The compound id, which may be a control placeholder such as
                ``[stau]``.

        Returns:
            str: The sanitised ``<cbkid>.csv`` filename.
        """
        return f"{_UNSAFE_FILENAME_CHARS.sub('', cbkid) or 'compound'}.csv"

    # Wagtail serves page URLs through ``^((?:[\w\-]+/)*)$``, so no path segment
    # may contain a dot: the artefact format is a segment of its own rather than
    # a file extension, and the compound id travels as a query parameter (it can
    # be a bracketed control placeholder). Downloaded files still arrive named
    # ``features.csv`` / ``<cbkid>.csv`` via Content-Disposition.
    @path("download/features/csv/")
    def download_features_csv(self, request: HttpRequest) -> FileResponse:
        """Serve the whole feature table as CSV."""
        return self._serve_artefact(request, "features.csv")

    @path("download/features/parquet/")
    def download_features_parquet(self, request: HttpRequest) -> FileResponse:
        """Serve the whole feature table as Parquet."""
        return self._serve_artefact(request, "features.parquet")

    @path("download/compound/")
    def download_compound(self, request: HttpRequest) -> HttpResponse:
        """Serve one compound's rows, filtered out of the Parquet table on the fly.

        Args:
            request: The incoming request; ``?cbkid=`` names the compound.

        Returns:
            HttpResponse: The compound's rows as a CSV attachment.

        Raises:
            Http404: If no compound was named, nothing is precomputed, or no row
                carries that ``cbkid``.
        """
        cbkid = request.GET.get("cbkid", "").strip()
        if not cbkid:
            raise Http404("No compound requested")

        features = self._artefact_dir() / "features.parquet"
        if not features.is_file():
            raise Http404("No feature table has been precomputed for this dataset")

        frame = pl.scan_parquet(features).filter(pl.col("cbkid") == cbkid).collect()
        if frame.is_empty():
            raise Http404("No rows for this compound")

        response = HttpResponse(frame.write_csv(), content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{self._attachment_filename(cbkid)}"'
        )
        return response

    @path("raw-images/")
    def raw_images(self, request: HttpRequest) -> HttpResponseRedirect:
        """Redirect to the upstream raw-image study for this screen.

        Raw imagery stays upstream: one plate is a ~228 GiB archive, so the
        portal links out (HTTP 302) instead of streaming or proxying a single
        byte of it.

        Args:
            request: The incoming request (unused; kept for route symmetry).

        Returns:
            HttpResponseRedirect: A 302 to this dataset's upstream study.

        Raises:
            Http404: If this dataset has no upstream study configured.
        """
        if not self.upstream_bia_url:
            raise Http404("No upstream image study configured")

        return HttpResponseRedirect(self.upstream_bia_url)
