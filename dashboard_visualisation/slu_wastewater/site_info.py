"""Functions to get site information from the given SLU data."""

import polars as pl


def get_sites_info(data: pl.DataFrame) -> list[tuple[str, int | str]]:
    """Return site information (site name and population) for methodology page.

    Args:
        data: DataFrame with at least "city" and "inhabitants" columns.

    Returns:
        A list-of-lists where the first row is a header and subsequent rows contain site info.

    """
    data = data.select(["city", "inhabitants"]).unique().sort("city")
    city_info = [("Site", "Num. of residents")]
    return city_info + data.rows()
