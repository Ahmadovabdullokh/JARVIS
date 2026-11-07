import unittest
from unittest.mock import Mock, patch

from app import persona
from app.main import get_chat_mode, set_chat_mode
from launcher import JarvisWindow


class ChatModeTests(unittest.TestCase):

    def tearDown(self):
        set_chat_mode("tasks")

    def test_appendix_chat(self):
        appendix = persona.mode_system_appendix("chat")
        self.assertIn("РЕЖИМ ПРОСТОЙ БЕСЕДЫ", appendix)
        self.assertIn("без инструментов", appendix)

    def test_appendix_code(self):
        appendix = persona.mode_system_appendix("code")
        self.assertIn("РЕЖИМ КОДА", appendix)
        self.assertIn("automation_copilot_fix", appendix)

    def test_appendix_tasks_empty(self):
        self.assertEqual(persona.mode_system_appendix("tasks"), "")

    def test_appendix_unknown_falls_back(self):
        self.assertEqual(persona.mode_system_appendix("мусор"), "")
        self.assertEqual(persona.mode_system_appendix(None), "")

    def test_system_prompt_includes_appendix(self):
        prompt = (
            persona.build_system_prompt()
            + persona.mode_system_appendix("code")
        )
        self.assertIn("РЕЖИМ КОДА", prompt)
        self.assertIn("JARVIS", prompt)

    def test_mode_roundtrip(self):
        self.assertEqual(set_chat_mode("code"), "code")
        self.assertEqual(get_chat_mode(), "code")
        self.assertEqual(set_chat_mode("chat"), "chat")
        self.assertEqual(get_chat_mode(), "chat")

    def test_mode_normalization(self):
        self.assertEqual(get_chat_mode("CHAT"), "chat")
        self.assertEqual(
            get_chat_mode("несуществующий"),
            "tasks",
        )
        set_chat_mode("code")
        self.assertEqual(get_chat_mode("мусор"), "tasks")

    @patch("launcher.submit_chat_message")
    def test_chat_submission_uses_selected_mode(self, submit):
        window = JarvisWindow.__new__(JarvisWindow)
        window.chat_input = Mock()
        window.chat_input.get.return_value = "исправь ошибку"
        window._chat_placeholder_active = False
        window.running = True
        window.jarvis_thread = Mock()
        window.jarvis_thread.is_alive.return_value = True
        window.send_button = Mock()
        window.mode_var = Mock()
        window.mode_var.get.return_value = "Код"
        window.mode_labels = {"Код": "code"}

        self.assertEqual(window.send_chat_message(), "break")
        submit.assert_called_once_with("исправь ошибку", mode="code")

    @patch("launcher.submit_chat_message")
    def test_chat_submission_error_is_reported(self, submit):
        submit.side_effect = RuntimeError("queue unavailable")
        window = JarvisWindow.__new__(JarvisWindow)
        window.chat_input = Mock()
        window.chat_input.get.return_value = "исправь ошибку"
        window._chat_placeholder_active = False
        window.running = True
        window.jarvis_thread = Mock()
        window.jarvis_thread.is_alive.return_value = True
        window.send_button = Mock()
        window.mode_var = Mock()
        window.mode_var.get.return_value = "Код"
        window.mode_labels = {"Код": "code"}
        window._append_chat_message = Mock()

        self.assertEqual(window.send_chat_message(), "break")
        window.send_button.configure.assert_called_with(state="normal")
        window._append_chat_message.assert_called()
        self.assertIn(
            "Не удалось отправить",
            window._append_chat_message.call_args.args[1],
        )


if __name__ == "__main__":
    unittest.main()