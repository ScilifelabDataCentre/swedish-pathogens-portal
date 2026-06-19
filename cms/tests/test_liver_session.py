"""Tests for liver resource session helpers."""

from django.contrib.sessions.backends.cache import SessionStore
from django.test import RequestFactory, SimpleTestCase

from cms.services.liver_resource.session import (
    SESSION_KEY,
    clear_de_session,
    de_data_from_session,
    get_de_session,
    get_session_cutoff,
    store_de_session,
    update_session_cutoff,
)


class TestLiverSession(SimpleTestCase):
    """Verify DE upload session storage."""

    def setUp(self) -> None:
        """Create a request with an empty session."""
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        session = SessionStore()
        session.create()
        self.request.session = session

    def test_store_and_get_de_session(self) -> None:
        """Test parsed DE data round-trips through the session."""
        de_data = {
            "header": ["logFC", "adj.P.Val"],
            "genes": ["ENSG00000000003"],
            "data": {"ENSG00000000003": {"logFC": 1.0, "adj.P.Val": 0.01}},
        }
        store_de_session(self.request, de_data=de_data, filename="example.txt", cutoff="standard")

        session = get_de_session(self.request)
        if session is None:
            self.fail("Expected session data after store_de_session")
        self.assertEqual(session["filename"], "example.txt")
        self.assertEqual(session["cutoff"], "standard")
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
        clear_de_session(self.request)
        self.assertIsNone(get_de_session(self.request))
        self.assertNotIn(SESSION_KEY, self.request.session)
