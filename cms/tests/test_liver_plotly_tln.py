"""Tests for liver resource Plotly TLN figure builder."""

from django.test import SimpleTestCase

from cms.services.liver_resource.computation import (
    classify_genes,
    compute_module_ratios,
    get_module_gene_sets,
    parse_de_file,
)
from cms.services.liver_resource.plotly_tln import (
    build_base_figure,
    build_base_figure_json,
    build_coloured_figure,
    build_coloured_figure_json,
    clear_plotly_layout_cache,
    count_leaf_markers,
)
from cms.services.liver_resource.reference_data import (
    EXPECTED_LEAF_COUNT,
    clear_reference_data_cache,
    get_data_root,
)


class TestLiverPlotlyTln(SimpleTestCase):
    """Verify Plotly TLN figures are built with the expected structure."""

    def tearDown(self) -> None:
        """Clear cached reference and layout data between tests."""
        clear_reference_data_cache()
        clear_plotly_layout_cache()

    def test_build_base_figure_has_three_traces(self) -> None:
        """Test base figure includes edges, internal nodes, and leaf modules."""
        figure = build_base_figure()
        self.assertEqual(len(figure.data), 3)

    def test_build_coloured_figure_has_colorbar_trace(self) -> None:
        """Test coloured figure adds a colorbar trace."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        classified = classify_genes(de_data, "standard")
        ratios = compute_module_ratios(de_data["genes"], classified, get_module_gene_sets())
        figure = build_coloured_figure(ratios, cutoff="standard")
        self.assertEqual(len(figure.data), 4)

    def test_base_figure_json_has_leaf_customdata(self) -> None:
        """Test serialised base figure exposes module ids on leaf markers."""
        figure_json = build_base_figure_json()
        self.assertIn("data", figure_json)
        self.assertIn("layout", figure_json)
        self.assertEqual(count_leaf_markers(figure_json), EXPECTED_LEAF_COUNT)

        leaf_trace = next(trace for trace in figure_json["data"] if trace.get("customdata"))
        self.assertEqual(len(leaf_trace["customdata"]), EXPECTED_LEAF_COUNT)
        self.assertEqual(leaf_trace["customdata"][0], "1")

    def test_coloured_figure_json_leaf_colours_are_hex(self) -> None:
        """Test coloured figure serialises hex marker colours for all modules."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        classified = classify_genes(de_data, "standard")
        ratios = compute_module_ratios(de_data["genes"], classified, get_module_gene_sets())
        figure_json = build_coloured_figure_json(ratios, cutoff="standard")

        leaf_trace = next(trace for trace in figure_json["data"] if trace.get("customdata"))
        colours = leaf_trace["marker"]["color"]
        self.assertEqual(len(colours), EXPECTED_LEAF_COUNT)
        for colour in colours:
            self.assertRegex(colour, r"^#[0-9a-f]{6}$")

    def test_figure_json_is_postgres_safe(self) -> None:
        """Test figure JSON contains no NaN or Infinity values."""
        figure_json = build_base_figure_json()
        serialised = str(figure_json)
        self.assertNotIn("NaN", serialised)
        self.assertNotIn("Infinity", serialised)
