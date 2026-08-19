"""Tests for liver resource reference data loading."""

from pathlib import Path

from django.test import SimpleTestCase, override_settings

from dashboard_visualisation.liver_resource.reference_data import (
    EXPECTED_LEAF_COUNT,
    EXPECTED_MODULE_COUNT,
    EXPECTED_VERTEX_COUNT,
    clear_reference_data_cache,
    get_data_root,
    get_template_path,
    list_example_files,
    load_cyjs_layout,
    load_module_labels,
    load_modules,
    load_symbol_map,
    load_tln_graph,
)


class TestLiverReferenceData(SimpleTestCase):
    """Verify bundled liver reference data loads correctly."""

    def tearDown(self) -> None:
        """Clear cached reference data between tests."""
        clear_reference_data_cache()

    def test_data_root_exists(self) -> None:
        """Test that the default bundled data directory is present."""
        root = get_data_root()
        self.assertTrue(root.is_dir())
        self.assertTrue((root / "tln_graph.json").is_file())

    def test_load_tln_graph(self) -> None:
        """Test TLN graph vertex and leaf counts."""
        graph = load_tln_graph()
        self.assertEqual(len(graph["vertices"]), EXPECTED_VERTEX_COUNT)
        self.assertEqual(graph["meta"]["vertex_count"], EXPECTED_VERTEX_COUNT)
        self.assertEqual(len(graph["edges"]), graph["meta"]["edge_count"])

        degree: dict[str, int] = {vertex["name"]: 0 for vertex in graph["vertices"]}
        for edge in graph["edges"]:
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
        leaf_count = sum(1 for value in degree.values() if value == 1)
        self.assertEqual(leaf_count, EXPECTED_LEAF_COUNT)

    def test_load_modules(self) -> None:
        """Test all module gene lists load."""
        modules = load_modules()
        self.assertEqual(len(modules), EXPECTED_MODULE_COUNT)
        module_ids = range(1, EXPECTED_MODULE_COUNT + 1)
        self.assertTrue(all(modules[module_id] for module_id in module_ids))

    def test_load_cyjs_layout(self) -> None:
        """Test layout positions exist for every graph vertex."""
        graph = load_tln_graph()
        layout = load_cyjs_layout()
        vertex_names = {vertex["name"] for vertex in graph["vertices"]}
        self.assertTrue(vertex_names.issubset(layout.keys()))

    def test_load_symbol_map(self) -> None:
        """Test Ensembl to symbol mapping loads."""
        symbol_map = load_symbol_map()
        self.assertGreater(len(symbol_map), 40_000)

    def test_load_module_labels(self) -> None:
        """Test module label mapping loads."""
        labels = load_module_labels()
        self.assertGreater(len(labels), 0)

    def test_list_example_files(self) -> None:
        """Test bundled example DE files are discoverable."""
        examples = list_example_files()
        self.assertEqual(len(examples), 3)
        names = {path.name for path in examples}
        self.assertIn("HCC-Control.txt", names)

    def test_template_path(self) -> None:
        """Test upload template file exists."""
        template = get_template_path()
        self.assertTrue(template.is_file())
        content = template.read_text(encoding="utf-8")
        self.assertIn("logFC", content)
        self.assertIn("adj.P.Val", content)

    @override_settings(LIVER_RESOURCE_DATA_ROOT=Path("/nonexistent"))
    def test_missing_data_root_raises(self) -> None:
        """Test loading fails clearly when data root is misconfigured."""
        clear_reference_data_cache()
        with self.assertRaises(FileNotFoundError):
            load_tln_graph()
