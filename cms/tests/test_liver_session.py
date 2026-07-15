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
    update_session_cutoff,
)
from dashboard_visualisation.liver_resource.session_storage import SESSIONS_SUBDIR


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
        sessions_root = Path(settings.MEDIA_ROOT) / SESSIONS_SUBDIR
        if sessions_root.is_dir():
            shutil.rmtree(sessions_root, ignore_errors=True)

    def test_store_and_get_de_session(self) -> None:
        """Test parsed DE data round-trips through the session."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt", cutoff="standard")

        session_meta = self.request.session[SESSION_KEY]
        self.assertIn("storage_id", session_meta)
        self.assertNotIn("genes", session_meta["files"][0])

        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected session data after store_de_session")
        self.assertEqual(session["files"][0]["filename"], "example.txt")
        self.assertEqual(session["cutoff"], "standard")
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
        store_de_uploads(self.request, uploads=uploads, cutoff="top500")
        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected session data after store_de_uploads")
        self.assertEqual(len(session["files"]), 2)
        self.assertEqual(de_uploads_from_session(session)[1][0], "b.txt")

    def test_legacy_inline_session_payload(self) -> None:
        """Test older inline session payloads still hydrate correctly."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        self.request.session[SESSION_KEY] = {
            "cutoff": "standard",
            "files": [{"filename": "legacy.txt", **de_data}],
        }
        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected legacy session data to hydrate")
        self.assertEqual(session["files"][0]["filename"], "legacy.txt")
        self.assertEqual(de_data_from_session(session), de_data)

    def test_update_session_cutoff(self) -> None:
        """Test cutoff can be changed without re-uploading."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt")
        update_session_cutoff(self.request, "top500")
        self.assertEqual(get_session_cutoff(self.request), "top500")

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
        self.assertFalse((Path(settings.MEDIA_ROOT) / SESSIONS_SUBDIR / storage_id).exists())
