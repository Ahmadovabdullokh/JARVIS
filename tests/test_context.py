import unittest

from app.context import ContextBuilder, build_context


class _FakeMemory:
    def __init__(self, facts):
        self._facts = facts
        self.calls = []

    def search(self, query, limit=10):
        self.calls.append((query, limit))
        return self._facts[:limit]


class _FakeSessions:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, limit=20):
        return self._hits[:limit]


class _FakeRag:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, limit=5):
        return self._hits[:limit]


class ContextBuilderTests(unittest.TestCase):

    def test_builds_all_sections(self):
        builder = ContextBuilder(
            memory=_FakeMemory(["люблю тёмную тему"]),
            sessions=_FakeSessions([
                {"role": "user", "content": "включи музыку"},
            ]),
            rag=_FakeRag([
                {"source": "notes.md", "text": "заметка про тему"},
            ]),
        )
        block = builder.build("тема")
        self.assertIn("Память и предпочтения", block)
        self.assertIn("люблю тёмную тему", block)
        self.assertIn("Из прошлых разговоров", block)
        self.assertIn("включи музыку", block)
        self.assertIn("Связанные локальные документы", block)
        self.assertIn("notes.md", block)

    def test_empty_query_returns_empty(self):
        builder = ContextBuilder(memory=_FakeMemory(["x"]))
        self.assertEqual(builder.build(""), "")

    def test_no_sources_returns_empty(self):
        self.assertEqual(ContextBuilder().build("что-то"), "")

    def test_truncates_to_max_chars(self):
        builder = ContextBuilder(
            memory=_FakeMemory(["a" * 5000]),
        )
        block = builder.build("x", max_chars=100)
        self.assertLessEqual(len(block), 101)
        self.assertTrue(block.endswith("…"))

    def test_failing_source_is_ignored(self):
        class Boom:
            def search(self, *a, **k):
                raise RuntimeError("boom")

        block = build_context(
            "q",
            memory=Boom(),
            sessions=_FakeSessions([
                {"role": "user", "content": "ok"},
            ]),
        )
        self.assertIn("ok", block)


if __name__ == "__main__":
    unittest.main()
