import unittest

from app.config import (
    apply_profile,
    get_active_profile,
    get_profiles,
    profile_names,
)


class ProfileTests(unittest.TestCase):

    def _config(self):
        return {
            "agent": {"max_iterations": 12, "autonomy": "balanced"},
            "speak_text": True,
            "active_profile": "default",
            "profiles": {
                "work": {
                    "agent": {"autonomy": "full"},
                    "speak_text": False,
                },
                "night": {"tts": {"rate": 150}},
            },
        }

    def test_profile_names(self):
        self.assertEqual(
            profile_names(self._config()),
            ["night", "work"],
        )

    def test_active_profile_default(self):
        self.assertEqual(get_active_profile({}), "default")
        self.assertEqual(get_active_profile(self._config()), "default")

    def test_apply_profile_deep_merges(self):
        merged = apply_profile(self._config(), "work")
        self.assertEqual(merged["agent"]["autonomy"], "full")
        self.assertEqual(merged["agent"]["max_iterations"], 12)
        self.assertFalse(merged["speak_text"])
        self.assertEqual(merged["active_profile"], "work")

    def test_apply_profile_does_not_mutate_source(self):
        config = self._config()
        apply_profile(config, "work")
        self.assertEqual(config["agent"]["autonomy"], "balanced")
        self.assertTrue(config["speak_text"])
        self.assertEqual(config["active_profile"], "default")

    def test_unknown_profile_is_noop(self):
        config = self._config()
        merged = apply_profile(config, "missing")
        self.assertEqual(merged["active_profile"], "default")
        self.assertEqual(get_profiles(config), config["profiles"])


if __name__ == "__main__":
    unittest.main()
