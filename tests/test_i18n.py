import unittest

from app import i18n


class I18nTests(unittest.TestCase):

    def setUp(self):
        i18n.clear_cache()
        i18n.set_language("ru")

    def tearDown(self):
        i18n.set_language("ru")

    def test_russian_strings(self):
        self.assertEqual(i18n.t("status.ready.label"), "READY")
        self.assertIn("Ожидаю", i18n.t("status.ready.description"))

    def test_english_strings(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("status.ready.label"), "READY")
        self.assertIn("Awaiting", i18n.t("status.ready.description"))

    def test_unknown_key_returns_default(self):
        self.assertEqual(
            i18n.t("nope.missing", default="fallback"),
            "fallback",
        )
        self.assertEqual(i18n.t("nope.missing"), "nope.missing")

    def test_format_placeholders(self):
        i18n.set_language("en")
        value = i18n.t("profile.changed", name="work")
        self.assertIn("work", value)

    def test_normalizes_language(self):
        self.assertEqual(i18n.set_language("en-US"), "en")
        self.assertEqual(i18n.set_language("RU"), "ru")
        self.assertEqual(i18n.set_language("de"), "ru")

    def test_available_languages(self):
        languages = i18n.available_languages()
        self.assertIn("ru", languages)
        self.assertIn("en", languages)


if __name__ == "__main__":
    unittest.main()
