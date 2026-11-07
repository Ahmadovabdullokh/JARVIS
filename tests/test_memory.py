import tempfile
import unittest
from pathlib import Path

from app.memory import Memory


class MemoryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "memory.json"
        self.memory = Memory(path=self.path, max_facts=3)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_remember_and_summary(self):
        self.assertTrue(self.memory.remember("Пользователя зовут Ахмад"))
        self.assertIn(
            "Пользователя зовут Ахмад",
            self.memory.summary(),
        )

    def test_duplicate_fact_is_ignored(self):
        self.memory.remember("Любимый браузер — Chrome")
        self.assertFalse(
            self.memory.remember("любимый браузер — chrome")
        )
        self.assertEqual(len(self.memory.facts()), 1)

    def test_facts_are_limited(self):
        for index in range(5):
            self.memory.remember(f"Факт {index}")

        self.assertEqual(
            self.memory.facts(),
            ["Факт 2", "Факт 3", "Факт 4"],
        )

    def test_profile_and_forget(self):
        self.memory.set_profile("Имя пользователя", "Ахмад")
        self.assertIn("Имя пользователя: Ахмад", self.memory.summary())

        self.memory.forget_all()
        self.assertEqual(self.memory.summary(), "")

    def test_data_persists_between_instances(self):
        self.memory.remember("Тестовый факт")

        restored = Memory(path=self.path)
        self.assertEqual(restored.facts(), ["Тестовый факт"])


if __name__ == "__main__":
    unittest.main()
