"""Function to get information about the most recent data in the dataset."""

import polars as pl


def get_recent_data_info(data: pl.DataFrame) -> dict:
    """Return information summarising the most recent sample date.

    Args:
        data: DataFrame which must contain "sampling_date", "city",
        "inhabitants", "target", "category".

    Returns:
        Dictionary with relevant recent data summary.

    """
    sampling_date = data["sampling_date"].max()
    recent_data = data.filter(pl.col("sampling_date") == sampling_date)
    recent_data_pop = recent_data.select(["city", "inhabitants"]).unique().sort("city")
    recent_data_cities = recent_data_pop["city"].to_list()
    sampling_sites_pop = round((recent_data_pop["inhabitants"].sum() / 10587710) * 100)

    if len(recent_data_cities) > 1:
        sampling_sites = f"{', '.join(recent_data_cities[:-1])} and {recent_data_cities[-1]}."
    else:
        sampling_sites = f"{recent_data_cities[0]}."

    summary = (
        recent_data.group_by("target")
        .agg(
            pl.col("category").count().alias("Analysed"),
            (pl.col("category") == "Positive sample").sum().alias("Positive"),
            (pl.col("category") != "Invalid sample").sum().alias("Valid"),
        )
        .sort("target")
    )
    sample_summary = [("Target", "Analysed", "Positive", "Valid")] + summary.rows()

    return {
        "sampling_date": sampling_date,
        "sampling_sites": sampling_sites,
        "sampling_sites_pop": sampling_sites_pop,
        "sample_summary": sample_summary,
    }
