import unittest
from datetime import datetime

from app import persona


class PersonaTests(unittest.TestCase):

    def test_time_greeting(self):
        self.assertEqual(
            persona.get_time_greeting(datetime(2026, 10, 27, 8)),
            "Доброе утро",
        )
        self.assertEqual(
            persona.get_time_greeting(datetime(2026, 10, 27, 14)),
            "Добрый день",
        )
        self.assertEqual(
            persona.get_time_greeting(datetime(2026, 10, 27, 20)),
            "Добрый вечер",
        )
        self.assertEqual(
            persona.get_time_greeting(datetime(2026, 10, 27, 2)),
            "Доброй ночи",
        )

    def test_startup_line_addresses_user(self):
        line = persona.startup_line(
            {"persona": {"address": "сэр", "name": "JARVIS"}},
            now=datetime(2026, 10, 27, 20),
        )

        self.assertIn("Добрый вечер, сэр", line)
        self.assertIn("Все системы в норме", line)

    def test_address_result_avoids_duplicate_address(self):
        self.assertEqual(
            persona.address_result(
                "Открываю Telegram.",
                {"persona": {"address": "сэр"}},
            ),
            "Сэр, открываю Telegram.",
        )
        self.assertEqual(
            persona.address_result(
                "Сэр, открываю Telegram.",
                {"persona": {"address": "сэр"}},
            ),
            "Сэр, открываю Telegram.",
        )
        self.assertEqual(
            persona.address_result(
                "Приветствую, сэр.",
                {"persona": {"address": "сэр"}},
            ),
            "Приветствую, сэр.",
        )

    def test_clean_for_speech_removes_markdown(self):
        cleaned = persona.clean_for_speech(
            "## Отчёт\n**Готово**, сэр. `код` [ссылка](https://x.y) 🙂"
        )

        self.assertNotIn("*", cleaned)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("🙂", cleaned)
        self.assertIn("Готово", cleaned)

    def test_system_prompt_contains_personality_and_memory(self):
        prompt = persona.build_system_prompt(
            {"persona": {"address": "сэр", "name": "JARVIS"}},
            "Имя пользователя: Ахмад.",
        )

        self.assertIn("JARVIS", prompt)
        self.assertIn("сэр", prompt)
        self.assertIn("Имя пользователя: Ахмад", prompt)
        self.assertIn("screen_send", prompt)

    def test_build_system_prompt_accepts_normalized_config(self):
        prompt = persona.build_system_prompt(
            {"address": "сэр", "name": "JARVIS"},
        )

        self.assertIn("JARVIS", prompt)


if __name__ == "__main__":
    unittest.main()
