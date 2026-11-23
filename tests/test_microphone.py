import unittest

from app import main as assistant_main
from app.status import get_status
from app.ui_bridge import UiBridge


class MicrophoneToggleTests(unittest.TestCase):
    def tearDown(self):
        assistant_main.set_microphone_enabled(True)

    def test_set_and_toggle_microphone_state(self):
        self.assertTrue(assistant_main.microphone_enabled())

        self.assertFalse(assistant_main.set_microphone_enabled(False))
        self.assertFalse(assistant_main.microphone_enabled())
        self.assertEqual(get_status(), "mic_off")

        self.assertTrue(assistant_main.toggle_microphone())
        self.assertTrue(assistant_main.microphone_enabled())
        self.assertEqual(get_status(), "listening")

    def test_bridge_exposes_microphone_toggle(self):
        bridge = UiBridge()
        result = bridge.set_microphone({"enabled": False})
        self.assertEqual(result, {"enabled": False})
        self.assertFalse(assistant_main.microphone_enabled())

        result = bridge.set_microphone({})
        self.assertEqual(result, {"enabled": True})
        self.assertTrue(assistant_main.microphone_enabled())


if __name__ == "__main__":
    unittest.main()
