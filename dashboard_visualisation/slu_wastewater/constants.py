"""Constant variables/values for SLU wastewater dashboard visualisation."""

# Viruses of interest i.e. only these virus data are used in the visualisation.
VIRUSES_OF_INTEREST = ["Influenza A virus", "Influenza B virus", "RSV", "SARS CoV-2"]

# List of expected columns in the uploaded CSV file
expected_columns = [
    "target",
    "sampling_date",
    "city",
    "inhabitants",
    "copies_l",
    "pmmov_normalised",
    "copies_day_inhabitant",
    "category",
]

# Dictionary mapping city names to their corresponding color and symbol for plotting
cities_graph_info = {
    "Gävle": {"colour": "#d6604d", "symbol": "hourglass"},
    "Göteborg": {"colour": "#9400d3", "symbol": "cross"},
    "Helsingborg": {"colour": "#efb261", "symbol": "square"},
    "Jönköping": {"colour": "#ffa500", "symbol": "cross"},
    "Kalmar": {"colour": "#f4a582", "symbol": "hourglass"},
    "Karlstad": {"colour": "#67001f", "symbol": "square"},
    "Linköping": {"colour": "#b2182b", "symbol": "cross"},
    "Luleå": {"colour": "#2166ac", "symbol": "cross"},
    "Malmö": {"colour": "#4393c3", "symbol": "square"},
    "Örebro": {"colour": "#b8860b", "symbol": "square"},
    "Östersund": {"colour": "#997950", "symbol": "hourglass"},
    "Östhammar": {"colour": "#778899", "symbol": "hourglass"},
    "Stockholm-Bromma": {"colour": "#000000", "symbol": "cross"},
    "Stockholm-Grödinge": {"colour": "#ff00ff", "symbol": "square"},
    "Stockholm-Henriksdal": {"colour": "#4adede", "symbol": "cross"},
    "Stockholm-Käppala": {"colour": "#ffd700", "symbol": "square"},
    "Umeå": {"colour": "#053061", "symbol": "hourglass"},
    "Uppsala": {"colour": "#663399", "symbol": "square"},
    "Västerås": {"colour": "#b691d2", "symbol": "hourglass"},
}

# Dictionary mapping city names to their corresponding display names for plotting
city_display_names = {
    "Gavle": "Gävle",
    "Goteborg": "Göteborg",
    "Helsingborg": "Helsingborg",
    "Jonkoping": "Jönköping",
    "Kalmar": "Kalmar",
    "Karlstad": "Karlstad",
    "Linkoping": "Linköping",
    "Lulea": "Luleå",
    "Malmo": "Malmö",
    "Orebro": "Örebro",
    "Ostersund": "Östersund",
    "Osthammar": "Östhammar",
    "Stockholm-Bromma": "Stockholm-Bromma",
    "Stockholm-Grodinge": "Stockholm-Grödinge",
    "Stockholm-Henriksdal": "Stockholm-Henriksdal",
    "Stockholm-Kappala": "Stockholm-Käppala",
    "Umea": "Umeå",
    "Uppsala": "Uppsala",
    "Vasteras": "Västerås",
}

# Dictionary mapping years to their corresponding color for plotting
yearcolors_map = {
    "2023": "#92c5de",
    "2024": "#f4a582",
    "2025": "#32c37d",
    "2026": "#b2182b",
}

# Dictionary mapping sample categories to their corresponding color for heatmap plotting
hmapcolors_map = {
    "Invalid sample": "#d6604d",
    "Negative sample": "#b691d2",
    "Positive sample": "#2166ac",
}
hmapcolors = list(hmapcolors_map.values())

# Common colors and settings for plots
bgcolor = "#ffffff"
gridcolor = "#e8e8e8"
linecolor = "#d6d6d6"

# Base settings for Plotly to convert figures to HTML
plotly_to_html_settings = {
    "include_plotlyjs": False,
    "full_html": False,
}

# Dictionary mapping normalization methods to their corresponding labels
norm_methods_map = {
    "pmmov_normalised": "PMMoV",
    "copies_day_inhabitant": "Wastewater flow",
    "copies_l": "None (copies/litre)",
}

# Dictionary mapping timeseries types to their corresponding labels
timeseries_map = {
    "1": "Weekly",
    "2": "Rolling average, 2 weeks",
    "3": "Rolling average, 3 weeks",
    "4": "Rolling average, 4 weeks",
}

# Common settings for axes and legends in plots
common_axes_settings = {
    "title": "",
    "linewidth": 0.8,
    "linecolor": linecolor,
    "mirror": True,
    "zerolinecolor": bgcolor,
}

# Base settings for scatter plot axes in plots
scatter_axes_settings = {
    "matches": None,
    "showgrid": True,
    "gridcolor": gridcolor,
    "gridwidth": 0.8,
    **common_axes_settings,
}

# Base settings for legend in plots
base_legend = {
    "title": "",
    "itemsizing": "constant",
    "borderwidth": 0.8,
    "bordercolor": linecolor,
}

# Settings for horizontal legend in plots
horizontal_legend = {
    "orientation": "h",
    "x": 0.5,
    "xanchor": "center",
    "yanchor": "bottom",
    **base_legend,
}

# Margin settings for plots
zero_margin = {
    "t": 0,
    "r": 10,
    "b": 0,
    "l": 0,
}
