"""Tests for liver resource session helpers."""

import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.backends.cache import SessionStore
from django.test import RequestFactory, TestCase

from dashboard_visualisation.liver_resource.session import (
    SESSION_KEY,
    clear_de_session,
    de_data_from_session,
    de_uploads_from_session,
    get_de_session,
    get_session_cutoff,
    store_de_session,
    store_de_uploads,
    update_session_controls,
)
from dashboard_visualisation.liver_resource.session_storage import (
    get_sessions_root,
    write_uploads,
)


class TestLiverSession(TestCase):
    """Verify DE upload session storage."""

    def setUp(self) -> None:
        """Create a request with an empty session."""
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        session = SessionStore()
        session.create()
        self.request.session = session

    def tearDown(self) -> None:
        """Remove on-disk liver session payloads created during tests."""
        sessions_root = get_sessions_root()
        if sessions_root.is_dir():
            shutil.rmtree(sessions_root, ignore_errors=True)

    def test_store_and_get_de_session(self) -> None:
        """Test parsed DE data round-trips through the session."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt", adj_p=0.05, logfc_fold=1.5)

        session_meta = self.request.session[SESSION_KEY]
        self.assertIn("storage_id", session_meta)
        self.assertNotIn("genes", session_meta["files"][0])

        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected session data after store_de_session")
        self.assertEqual(session["files"][0]["filename"], "example.txt")
        self.assertEqual(session["cutoff"], "0.05_1.5")
        self.assertEqual(session["adj_p"], 0.05)
        self.assertEqual(session["logfc_fold"], 1.5)
        self.assertEqual(de_data_from_session(session), de_data)

    def test_store_multiple_uploads(self) -> None:
        """Test multiple parsed DE files round-trip through the session."""
        uploads = [
            (
                "a.txt",
                {
                    "header": ["logFC", "adj.P.Val"],
                    "genes": ["ENSG00000000003"],
                    "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
                },
            ),
            (
                "b.txt",
                {
                    "header": ["logFC", "adj.P.Val"],
                    "genes": ["ENSG00000000003"],
                    "data": {"ENSG00000000003": {"logFC": -1.0, "adj.P.Val": 0.01}},
                },
            ),
        ]
        store_de_uploads(self.request, uploads=uploads, adj_p=0.01, logfc_fold=2.0)
        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected session data after store_de_uploads")
        self.assertEqual(len(session["files"]), 2)
        self.assertEqual(session["cutoff"], "0.01_2")
        self.assertEqual(de_uploads_from_session(session)[1][0], "b.txt")

    def test_legacy_inline_session_payload(self) -> None:
        """Test older inline session payloads still hydrate correctly."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        self.request.session[SESSION_KEY] = {
            "cutoff": "0.05_1.5",
            "files": [{"filename": "legacy.txt", **de_data}],
        }
        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected legacy session data to hydrate")
        self.assertEqual(session["files"][0]["filename"], "legacy.txt")
        self.assertEqual(de_data_from_session(session), de_data)

    def test_update_session_controls(self) -> None:
        """Test thresholds can be changed without re-uploading."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt")
        update_session_controls(self.request, adj_p=0.001, logfc_fold=5.0)
        self.assertEqual(get_session_cutoff(self.request), "0.001_5")
        session = get_de_session(self.request)
        assert session is not None
        self.assertEqual(session["adj_p"], 0.001)
        self.assertEqual(session["logfc_fold"], 5.0)

    def test_clear_de_session(self) -> None:
        """Test session data is removed on clear."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt")
        storage_id = self.request.session[SESSION_KEY]["storage_id"]
        clear_de_session(self.request)
        self.assertIsNone(get_de_session(self.request))
        self.assertNotIn(SESSION_KEY, self.request.session)
        self.assertFalse((get_sessions_root() / storage_id).exists())

    def test_session_files_outside_media_root(self) -> None:
        """Visitor DE JSON must not be written under the public media tree."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt")
        storage_id = self.request.session[SESSION_KEY]["storage_id"]
        dest = get_sessions_root() / storage_id
        media_root = Path(settings.MEDIA_ROOT).resolve()
        self.assertTrue(dest.is_dir())
        self.assertFalse(dest.resolve().is_relative_to(media_root))
        legacy_media_path = media_root / "liver_resource_sessions" / storage_id
        self.assertFalse(legacy_media_path.exists())

    def test_write_uploads_rejects_non_hex_storage_id(self) -> None:
        """Path joins must reject traversal-style storage ids."""
        with self.assertRaises(ValueError):
            write_uploads("../escape", [("a.txt", {"header": [], "genes": [], "data": {}})])
