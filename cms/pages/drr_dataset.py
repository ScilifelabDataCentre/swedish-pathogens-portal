"""CMS page for a single Drug Repurposing Resource (DRR) dataset."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import polars as pl
import structlog
from django.core.cache import cache
from django.db import models
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.routable_page.models import RoutablePageMixin, path
from wagtail.search import index

from cms.pages.dashboard import DashboardPage
from cms.services.file_downloads import resolve_file_in_directory, serve_file_from_directory
from dashboard_visualisation.drr import artefact_dir, compound_label
from dashboard_visualisation.utils import plot_html_from_json

if TYPE_CHECKING:
    from pathlib import Path

    from cms.snippets.drr_dataset_data import DrrDatasetData

LOGGER = structlog.get_logger(__name__)

# Everything outside this set is dropped from a download's filename. Compound
# ids are not restricted to it — control placeholders such as ``[stau]`` are
# legitimate ``cbkid`` values — so this sanitises the header only.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

# The compound-index columns the pickers label from. ``name`` and ``kind`` are
# read when present rather than required: an index built without CBCS metadata
# carries neither, and the picker still has to offer every downloadable id.
# ``radar_key`` names the compound's per-compound radar on disk (FREYA-2636).
_COMPOUND_OPTION_COLUMNS = ("cbkid", "name", "kind", "radar_key")

# The radars, in page order, rendered by the page's own radar partial rather
# than placed as editorial PlotlyFigureBlocks (spec section 10, decision 7), so
# the compound picker always sits beside the figure it swaps. Only
# ``radar_compound`` is precomputed as a per-compound set, so it is the one
# figure the section 8.3 route serves.
_RADAR_FIGURES: tuple[dict[str, Any], ...] = (
    {
        "figure_id": "radar_compound",
        "alt_text": (
            "Radar chart of morphological feature groups, comparing treated wells "
            "with the infected DMSO baseline"
        ),
        "caption": "Pooled across every treated well until a compound is chosen.",
        "height": 600,
    },
    {
        "figure_id": "radar_infected",
        "alt_text": (
            "Radar chart of the morphological feature groups most changed by "
            "infection, comparing uninfected wells with the infected DMSO baseline"
        ),
        "caption": (
            "Uninfected wells read against the infected DMSO baseline the input is normalised to."
        ),
        "height": 600,
    },
)
_COMPOUND_FIGURE_ID = "radar_compound"

# ``radar_compound``'s caption once a reader has picked a compound: the default
# caption describes the pooled view the swap replaces.
_SWAPPED_RADAR_CAPTION = (
    "One compound's treated wells, doses pooled, read against the infected DMSO baseline."
)

# Where the per-compound radar set lives inside the artefact directory.
_RADAR_SET_DIR = "figures/radar"

# Rendered radar HTML is cached like the shared figure block's, keyed on the
# data row's hash so a rebuild that changes a figure cannot serve the old one.
_RADAR_CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


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

    search_fields = DashboardPage.search_fields + [
        index.SearchField("organism"),
        index.SearchField("cell_line"),
        index.SearchField("screen_type"),
    ]

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
        """Add the DRR summary payload, the download URLs, the radars and both pickers."""
        context = super().get_context(request)
        context["summary"] = getattr(self.dashboard_data, "summary", {})

        download_urls = self._download_urls()
        if download_urls:
            context["download_urls"] = download_urls

        options = self._compound_options()

        # The download picker exists to submit to the per-compound slice, so it
        # is withheld unless that route can serve — otherwise every option 404s.
        if "compound_base" in download_urls and options:
            context["compounds"] = options

        figures = getattr(self.dashboard_data, "data", {}) or {}
        radar_figures = [
            self._radar_figure(settings, figures[settings["figure_id"]])
            for settings in _RADAR_FIGURES
            if figures.get(settings["figure_id"]) is not None
        ]
        if radar_figures:
            context["radar_figures"] = radar_figures

        # The radar picker is the other half of the download rule: it offers
        # only the compounds precompute wrote a radar for, so no option can 404
        # and no reader is shown a control that does nothing (spec section 8.3).
        # It also needs the figure it swaps to be on the page, or its target
        # would not exist and the swap would fail silently in the browser.
        radar_options = [option for option in options if option["radar_key"]]
        if radar_options and figures.get(_COMPOUND_FIGURE_ID) is not None:
            context["radar_compounds"] = radar_options
            context["radar_url"] = (self.url or "") + self.reverse_subpage("figure")
            context["radar_figure_id"] = _COMPOUND_FIGURE_ID

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

        Every unreadable index yields no options rather than an exception: this
        read happens on each page view, precompute writes the file in place, and
        the picker is an enhancement of a page whose header, figures and bulk
        downloads must survive a half-written or truncated generation. That is
        the same failure posture the figures already take.

        Returns:
            list[dict[str, str]]: ``cbkid`` / ``label`` / ``radar_key`` triples,
                compounds before controls and then by label; empty when no index
                is readable. ``radar_key`` is empty for a compound precompute
                wrote no radar for, which is what the figure picker filters on.
        """
        index = self._artefact_dir() / "compounds.parquet"
        if not index.is_file():
            return []

        try:
            present = pl.scan_parquet(index).collect_schema().names()
            if "cbkid" not in present:
                LOGGER.warning("drr.compounds.index_has_no_cbkid", path=str(index))
                return []

            columns = [column for column in _COMPOUND_OPTION_COLUMNS if column in present]
            rows = pl.read_parquet(index, columns=columns).to_dicts()
        except (OSError, pl.exceptions.PolarsError) as error:
            LOGGER.warning("drr.compounds.index_unreadable", path=str(index), error=str(error))
            return []

        # A null id is dropped rather than labelled: it names no downloadable
        # compound, and mixing None into the sort key would raise instead.
        options = sorted(
            (
                (
                    row.get("kind") == "control",
                    self._compound_label(row),
                    row["cbkid"],
                    row.get("radar_key") or "",
                )
                for row in rows
                if isinstance(row.get("cbkid"), str) and row["cbkid"].strip()
            ),
            key=lambda option: (option[0], option[1].casefold(), option[2]),
        )
        return [
            {"cbkid": cbkid, "label": label, "radar_key": radar_key}
            for _, label, cbkid, radar_key in options
        ]

    @staticmethod
    def _compound_label(row: dict[str, Any]) -> str:
        """Return one compound's picker label.

        Args:
            row: A ``compounds.parquet`` row: ``cbkid``, plus ``name`` and
                ``kind`` when the index carries them.

        Returns:
            str: ``<name> (<cbkid>)`` once the CBCS join annotated the compound,
                ``<cbkid> (control)`` for a non-CBCS control id, and the bare
                ``cbkid`` for a compound the join did not annotate. The rule is
                the precompute package's, so a swapped-in radar's title names
                the compound exactly as the control that asked for it does.
        """
        return compound_label(row["cbkid"], name=row.get("name"), kind=row.get("kind"))

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

    # ------------------------------------------------------------------ #
    # Figure swap (spec section 8.3)                                     #
    # ------------------------------------------------------------------ #

    def _radar_figure(
        self, settings: dict[str, Any], figure_json: dict[str, Any], cbkid: str = ""
    ) -> dict[str, Any]:
        """Render one radar into the context its partial reads.

        Args:
            settings: The figure's entry in ``_RADAR_FIGURES``.
            figure_json: The precomputed Plotly JSON.
            cbkid: The compound a per-compound radar was read for; empty for the
                default views. It keys the cache, so one compound's render can
                never be served for another's.

        Returns:
            dict[str, Any]: ``settings`` plus the rendered ``plot_html`` and the
                ``caveat`` the payload carries about itself.
        """
        figure_id = settings["figure_id"]
        height_px = int(settings["height"])
        file_hash = getattr(self.dashboard_data, "source_file_hash", "") or ""
        cache_key = f"drr_radar_html:{self.slug}:{figure_id}:{cbkid}:{file_hash}:{height_px}"

        plot_html = cache.get(cache_key)
        if plot_html is None:
            plot_html = plot_html_from_json(
                figure_json, height=f"{height_px}px", include_plotlyjs=False
            )
            if plot_html is not None:
                cache.set(cache_key, plot_html, _RADAR_CACHE_TIMEOUT_SECONDS)

        return {**settings, "plot_html": plot_html, "caveat": self._radar_caveat(figure_json)}

    @staticmethod
    def _radar_caveat(figure_json: dict[str, Any]) -> str:
        """Return the basis caveat precompute wrote into a radar's ``layout.meta``.

        It is rendered as page text beneath the chart rather than as a Plotly
        annotation, because annotation text does not wrap and a sentence this
        long is clipped at the plot's edge on a narrow viewport.

        Args:
            figure_json: The precomputed Plotly JSON.

        Returns:
            str: The caveat, or an empty string when the figure declares none.
        """
        meta = figure_json.get("layout", {}).get("meta") or {}
        return str(meta.get("caveat", "")) if isinstance(meta, dict) else ""

    def _radar_payload(self, cbkid: str) -> dict[str, Any]:
        """Read one compound's precomputed radar from disk.

        The filename is the key precompute derived and recorded on the compound
        index; the request's ``cbkid`` only ever looks that key up, so no
        request value reaches a path. The lookup then goes through the same
        traversal guard the downloads use.

        Args:
            cbkid: The compound id from the query string.

        Returns:
            dict[str, Any]: The figure's Plotly JSON.

        Raises:
            Http404: If the index is missing or unreadable, the compound has no
                radar, or the artefact is not on disk.
        """
        match = next(
            (option for option in self._compound_options() if option["cbkid"] == cbkid),
            None,
        )
        if match is None or not match["radar_key"]:
            raise Http404("No radar has been precomputed for this compound")

        artefact = resolve_file_in_directory(
            self._artefact_dir(), f"{_RADAR_SET_DIR}/{match['radar_key']}.json"
        )
        try:
            return json.loads(artefact.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            LOGGER.warning("drr.figure.unreadable_radar", path=str(artefact), error=str(error))
            raise Http404("Radar artefact is not readable") from error

    @path("figure/")
    def figure(self, request: HttpRequest) -> HttpResponse:
        """Serve one compound's radar as a server-rendered partial for an htmx swap.

        The ``cbkid`` only ever looks up the key precompute recorded on the
        compound index, so no request value reaches a path. It travels in the
        query string because control ids such as ``[stau]`` cannot sit in a
        path segment. The response goes through the same partial the page
        renders, so the swapped figure carries the same id, alt text and
        caveat, and repeated swaps keep working.

        Args:
            request: The incoming request; ``?cbkid=`` names the compound.

        Returns:
            HttpResponse: The radar partial.

        Raises:
            Http404: If no compound was named or the compound has no radar. The
                page then keeps the radar it already rendered.
        """
        cbkid = request.GET.get("cbkid", "").strip()
        if not cbkid:
            raise Http404("No compound requested")

        settings = {
            **next(
                figure for figure in _RADAR_FIGURES if figure["figure_id"] == _COMPOUND_FIGURE_ID
            ),
            "caption": _SWAPPED_RADAR_CAPTION,
        }
        return render(
            request,
            "cms/pages/drr/partials/radar_figure.html",
            {"figure": self._radar_figure(settings, self._radar_payload(cbkid), cbkid)},
        )

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
