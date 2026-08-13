"""Sample data for SLU WW dashboard tests."""

import polars as pl


def get_sample_data() -> pl.DataFrame:
    """Return representative sample data for dashboard tests."""

    return pl.DataFrame(
        {
            "sampling_date": [
                # Virus A — Goteborg
                "2023-01-10",
                "2023-01-17",
                "2023-01-24",
                "2024-01-10",
                "2024-01-17",
                "2024-01-24",
                # Virus A — Kalmar
                "2023-01-10",
                "2023-01-17",
                "2023-01-24",
                "2024-01-10",
                "2024-01-17",
                "2024-01-24",
                # Virus B — Goteborg
                "2023-01-10",
                "2023-01-17",
                "2023-01-24",
                "2024-01-10",
                "2024-01-17",
                "2024-01-24",
                # Virus B — Kalmar
                "2023-01-10",
                "2023-01-17",
                "2023-01-24",
                "2024-01-10",
                "2024-01-17",
                "2024-01-24",
            ],
            "city": [
                # Virus A — Goteborg
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                # Virus A — Kalmar
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
                # Virus B — Goteborg
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                "Goteborg",
                # Virus B — Kalmar
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
                "Kalmar",
            ],
            "target": [
                # Virus A — Goteborg
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                # Virus A — Kalmar
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                "virus_a",
                # Virus B — Goteborg
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
                # Virus B — Kalmar
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
                "virus_b",
            ],
            "category": [
                # Virus A — Goteborg
                "Positive sample",
                "Negative sample",
                "Positive sample",
                "Negative sample",
                "Positive sample",
                "Negative sample",
                # Virus A — Kalmar
                "Negative sample",
                "Positive sample",
                "Negative sample",
                "Positive sample",
                "Negative sample",
                "Positive sample",
                # Virus B — Goteborg
                "Negative sample",
                "Negative sample",
                "Positive sample",
                "Positive sample",
                "Negative sample",
                "Positive sample",
                # Virus B — Kalmar
                "Positive sample",
                "Negative sample",
                "Positive sample",
                "Negative sample",
                "Positive sample",
                "Negative sample",
            ],
            "inhabitants": [
                # Virus A — Goteborg
                600_000,
                600_000,
                600_000,
                600_000,
                600_000,
                600_000,
                # Virus A — Kalmar
                40_000,
                40_000,
                40_000,
                40_000,
                40_000,
                40_000,
                # Virus B — Goteborg
                600_000,
                600_000,
                600_000,
                600_000,
                600_000,
                600_000,
                # Virus B — Kalmar
                40_000,
                40_000,
                40_000,
                40_000,
                40_000,
                40_000,
            ],
            "pmmov_normalised": [
                # Virus A — Goteborg
                100.0,
                200.0,
                300.0,
                400.0,
                500.0,
                600.0,
                # Virus A — Kalmar
                200.0,
                300.0,
                400.0,
                500.0,
                600.0,
                700.0,
                # Virus B — Goteborg
                150.0,
                250.0,
                350.0,
                450.0,
                550.0,
                650.0,
                # Virus B — Kalmar
                250.0,
                350.0,
                450.0,
                550.0,
                650.0,
                750.0,
            ],
            "copies_day_inhabitant": [
                # Virus A — Goteborg
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                # Virus A — Kalmar
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                # Virus B — Goteborg
                1.5,
                2.5,
                3.5,
                4.5,
                5.5,
                6.5,
                # Virus B — Kalmar
                2.5,
                3.5,
                4.5,
                5.5,
                6.5,
                7.5,
            ],
            "copies_l": [
                # Virus A — Goteborg
                100.0,
                200.0,
                300.0,
                400.0,
                500.0,
                600.0,
                # Virus A — Kalmar
                200.0,
                300.0,
                400.0,
                500.0,
                600.0,
                700.0,
                # Virus B — Goteborg
                150.0,
                250.0,
                350.0,
                450.0,
                550.0,
                650.0,
                # Virus B — Kalmar
                250.0,
                350.0,
                450.0,
                550.0,
                650.0,
                750.0,
            ],
        }
    )
