"""Tests for the per-compound feature slice (FREYA-2580, spec section 8).

``download/compound/?cbkid=<id>`` filters ``features.parquet`` on the fly
(contract decision 3) rather than serving a precomputed per-compound file. The
id travels as a query parameter because Wagtail's page-serving pattern admits
neither the dots of a ``.csv`` suffix nor the brackets of a control placeholder.
"""

from django.test import RequestFactory

from cms.tests.test_drr_downloads import DrrDownloadRouteTestCase


class TestDrrCompoundDownload(DrrDownloadRouteTestCase):
    """The per-``cbkid`` slice route."""

    def compound(self, cbkid: str | None = None) -> object:
        """GET the per-compound slice.

        Args:
            cbkid: The compound id; omitted entirely when ``None``. The test
                client handles any percent-encoding needed.

        Returns:
            The test client response.
        """
        query = {} if cbkid is None else {"cbkid": cbkid}
        return self.client.get(self.page.url + "download/compound/", query)

    def test_valid_cbkid_returns_only_that_compounds_rows(self) -> None:
        """The slice contains the requested compound's rows and no others."""
        self.write_artefacts()

        response = self.compound("CBK1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="CBK1.csv"')
        body = response.content.decode()
        rows = body.strip().splitlines()
        self.assertEqual(len(rows), 3)  # header + the two CBK1 wells
        self.assertIn("cbkid", rows[0])
        self.assertNotIn("CBK2", body)
        self.assertNotIn("[stau]", body)

    def test_bracketed_control_id_is_served_with_a_sanitised_filename(self) -> None:
        """Control placeholders like ``[stau]`` are valid ids, not rejected input.

        The brackets are stripped from the attachment filename only, which keeps
        the header safe without narrowing which compounds can be downloaded.
        """
        self.write_artefacts()

        response = self.compound("[stau]")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="stau.csv"')
        self.assertIn("[stau]", response.content.decode())

    def test_unknown_cbkid_returns_404(self) -> None:
        """An id absent from the feature table 404s."""
        self.write_artefacts()

        self.assertEqual(self.compound("CBK999").status_code, 404)

    def test_partial_cbkid_does_not_match(self) -> None:
        """The filter is exact equality, not a prefix or substring match."""
        self.write_artefacts()

        self.assertEqual(self.compound("CBK").status_code, 404)

    def test_missing_cbkid_parameter_returns_404(self) -> None:
        """The route needs a compound; a bare request is not a whole-table download."""
        self.write_artefacts()

        self.assertEqual(self.compound().status_code, 404)
        self.assertEqual(self.compound("   ").status_code, 404)

    def test_missing_parquet_returns_404(self) -> None:
        """Without precomputed artefacts the slice 404s rather than erroring."""
        self.assertEqual(self.compound("CBK1").status_code, 404)

    def test_path_shaped_value_returns_404(self) -> None:
        """A path-shaped id resolves to no rows and never reaches the filesystem."""
        self.write_artefacts()

        self.assertEqual(self.compound("../../secret.txt").status_code, 404)

    def test_every_option_the_picker_offers_downloads(self) -> None:
        """No option 404s: each id the on-page picker offers serves its own rows (FREYA-2583).

        The picker builds its options from ``compounds.parquet`` while this route
        filters ``features.parquet``, so nothing but a test walking the offered
        set catches the two artefacts disagreeing — including on the bracketed
        control id, which only survives because it travels in the query string.
        """
        self.write_artefacts()
        self.write_compound_index()

        request = RequestFactory().get(self.page.url)
        options = self.page.get_context(request)["compounds"]

        self.assertEqual([option["cbkid"] for option in options], ["CBK2", "CBK1", "[stau]"])
        for option in options:
            with self.subTest(cbkid=option["cbkid"]):
                response = self.compound(option["cbkid"])
                self.assertEqual(response.status_code, 200)
                header, *rows = response.content.decode().strip().splitlines()
                column = header.split(",").index("cbkid")
                self.assertEqual({row.split(",")[column] for row in rows}, {option["cbkid"]})

    def test_extra_input_columns_are_preserved(self) -> None:
        """A wider feature table still slices, whatever extra columns an input carries."""
        self.write_artefacts(
            pert_iname=["remdesivir", "remdesivir", "aloxistatin", "staurosporine"]
        )

        response = self.compound("CBK1")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("pert_iname", body.splitlines()[0])
        self.assertIn("remdesivir", body)
