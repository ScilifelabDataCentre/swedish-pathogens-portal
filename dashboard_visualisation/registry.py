"""Visualization service registry for dashboard data.

Each dashboard has its own viz service module that reads a CSV file and
returns a dict of {figure_id: plotly_figure_json}. This module provides
the registry that dispatches to the correct service based on dashboard_slug.
"""

import importlib
from typing import Any

import structlog

from dashboard_visualisation.utils.uploads import SourceFile

LOGGER = structlog.get_logger(__name__)

# Register active (non-historic) dashboard slugs here, e.g.:
# "serology-statistics": "dashboard_visualisation.serology_statistics",
VIZ_MODULES: dict[str, str] = {
    "liver-resource": "dashboard_visualisation.liver_resource.figures",
    "serology-statistics": "dashboard_visualisation.serology_statistics",
    "slu-wastewater": "dashboard_visualisation.slu_wastewater",
    "variants-region-uppsala": "dashboard_visualisation.variants_region_uppsala",
    "recovac": "dashboard_visualisation.recovac",
}


def validate_source_columns(dashboard_slug: str, columns: list[str]) -> str | None:
    """Return an error message when columns fail dashboard-specific checks.

    Dashboards without a registered viz module, or without a column validator,
    skip slug-specific checks (generic CSV validation still applies).
    """
    module_path = VIZ_MODULES.get(dashboard_slug)
    if module_path is None:
        return None

    module = importlib.import_module(module_path)
    validate = getattr(module, "validate_source_columns", None)
    if validate is None:
        return None
    return validate(columns)


def validate_source_file(
    dashboard_slug: str,
    source_file: SourceFile,
    *,
    filename: str = "",
    size_bytes: int | None = None,
) -> tuple[bool, str | None]:
    """Dispatch optional dashboard-specific full-file validation.

    Use this when a dashboard cannot use the generic CSV path (for example
    limma DE ``.txt`` uploads or a multi-file ``.zip``). Same optional-hook
    pattern as :func:`validate_source_columns`.

    Returns:
        ``(False, None)`` — no custom validator; caller should run generic CSV
        checks (and :func:`validate_source_columns`).
        ``(True, None)`` — custom validator accepted the upload.
        ``(True, error)`` — custom validator rejected the upload.
    """
    module_path = VIZ_MODULES.get(dashboard_slug)
    if module_path is None:
        return False, None

    module = importlib.import_module(module_path)
    validate = getattr(module, "validate_source_file", None)
    if validate is None:
        return False, None
    return True, validate(source_file, filename=filename, size_bytes=size_bytes)


def generate_figures(
    dashboard_slug: str,
    source_file: SourceFile,
) -> dict[str, Any]:
    """Generate all Plotly figures for a dashboard from its source data file.

    Dispatches to the dashboard-specific viz service module. If no specific
    service exists for the given slug, returns an empty dict.

    Args:
        dashboard_slug: Identifies which viz service to use.
        source_file: Path or file-like object for the source data file.

    Returns:
        Dict mapping figure_id to Plotly figure JSON.
    """
    module_path = VIZ_MODULES.get(dashboard_slug)
    if module_path is None:
        LOGGER.info("dashboard_visualisation.unregistered_slug", dashboard_slug=dashboard_slug)
        return {}

    LOGGER.info(
        "dashboard_visualisation.generating_figures",
        dashboard_slug=dashboard_slug,
        module=module_path,
    )
    try:
        module = importlib.import_module(module_path)
        figures = module.generate_figures(source_file)
    except Exception as exc:
        LOGGER.warning(
            "dashboard_visualisation.generation_failed",
            dashboard_slug=dashboard_slug,
            module=module_path,
            error=str(exc),
            exc_info=True,
        )
        raise

    LOGGER.info(
        "dashboard_visualisation.generation_complete",
        dashboard_slug=dashboard_slug,
        figure_count=len(figures),
    )
    return figures
