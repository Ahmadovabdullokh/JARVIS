import tempfile
import unittest
from pathlib import Path

from app.rag import RagIndex
from app.sessions import SessionStore


class SessionSearchTests(unittest.TestCase):

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.store = SessionStore(path=Path(self._temp.name) / "s.sqlite")
        self.addCleanup(self.store.close)
        self.session_id = self.store.create_session("test")

    def test_search_finds_message(self):
        self.store.add_message(
            self.session_id, "user", "расскажи про квазар и пульсар"
        )
        self.store.add_message(
            self.session_id, "assistant", "квазары очень яркие"
        )
        hits = self.store.search("квазар")
        self.assertTrue(hits)
        self.assertTrue(
            any("квазар" in hit["content"].lower() for hit in hits)
        )
        self.assertIn("role", hits[0])
        self.assertIn("session_id", hits[0])

    def test_search_empty_query(self):
        self.assertEqual(self.store.search(""), [])

    def test_search_no_match(self):
        self.store.add_message(self.session_id, "user", "привет")
        self.assertEqual(self.store.search("космолет"), [])

    def test_history_roundtrip(self):
        self.store.add_message(self.session_id, "user", "вопрос")
        self.store.add_message(self.session_id, "assistant", "ответ")
        history = self.store.history(self.session_id)
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])


class RagSearchTests(unittest.TestCase):

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self.docs = root / "docs"
        self.docs.mkdir()
        (self.docs / "space.txt").write_text(
            "Квазар — это активное ядро галактики. Пульсар вращается.",
            encoding="utf-8",
        )
        self.index = RagIndex(path=root / "rag.sqlite")
        self.addCleanup(self.index.close)

    def test_index_and_search(self):
        report = self.index.index(self.docs)
        self.assertIn("Проиндексировано", report)
        self.assertGreaterEqual(self.index.stats()["chunks"], 1)
        hits = self.index.search("квазар")
        self.assertTrue(hits)
        self.assertTrue(
            any("квазар" in hit["text"].lower() for hit in hits)
        )
        self.assertTrue(hits[0]["source"].endswith("space.txt"))

    def test_search_no_terms(self):
        self.assertEqual(self.index.search(""), [])

    def test_clear(self):
        self.index.index(self.docs)
        self.index.clear()
        self.assertEqual(self.index.stats()["chunks"], 0)


if __name__ == "__main__":
    unittest.main()
