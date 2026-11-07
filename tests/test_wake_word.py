import unittest

from app.main import normalize_voice_text
from app.voice_normalizer import process_voice_text


class WakeWordTests(unittest.TestCase):

    def test_wake_word_is_detected_and_removed(self):
        text, has_wake = normalize_voice_text(
            "Джарвис, открой ютуб"
        )

        self.assertTrue(has_wake)
        self.assertEqual(text, "открой ютуб")

    def test_command_without_wake_word_is_marked(self):
        text, has_wake = normalize_voice_text("открой ютуб")

        self.assertFalse(has_wake)
        self.assertEqual(text, "открой ютуб")

    def test_only_wake_word_gives_empty_command(self):
        text, has_wake = normalize_voice_text("Джарвис")

        self.assertTrue(has_wake)
        self.assertEqual(text, "")

    def test_fuzzy_wake_word_variants(self):
        for phrase in (
            "дарвис открой блокнот",
            "дарвиса открой блокнот",
            "джарвиз открой блокнот",
            "жарвис открой блокнот",
            "равис открой блокнот",
            "равиз открой блокнот",
            "арвис открой блокнот",
            "джавис открой блокнот",
            "жавис открой блокнот",
            "чавис открой блокнот",
        ):
            text, has_wake = process_voice_text(phrase)
            self.assertTrue(has_wake, phrase)
            self.assertEqual(text, "открой блокнот", phrase)

    def test_wake_word_is_not_removed_inside_other_words(self):
        text, has_wake = process_voice_text("джарвисовый стиль")

        self.assertFalse(has_wake)
        self.assertIn("джарвисовый", text)

    def test_common_word_with_similar_ending_is_not_wake_word(self):
        text, has_wake = process_voice_text("сервис открой блокнот")

        self.assertFalse(has_wake)
        self.assertEqual(text, "сервис открой блокнот")

    def test_custom_wake_words_do_not_enable_jarvis_heuristics(self):
        text, has_wake = process_voice_text(
            "равис открой блокнот",
            wake_words=["компьютер"],
        )

        self.assertFalse(has_wake)
        self.assertTrue(text)

    def test_custom_wake_words_from_config(self):
        text, has_wake = process_voice_text(
            "компьютер открой блокнот",
            wake_words=["компьютер"],
        )

        self.assertTrue(has_wake)
        self.assertEqual(text, "открой блокнот")


if __name__ == "__main__":
    unittest.main()
