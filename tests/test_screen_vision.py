import base64
import io
import queue
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from app import main as assistant_main
from app.llm_client import LLMClient
from app.pc_agent import PCAgent


class ScreenVisionTests(unittest.TestCase):

    def test_analyze_screen_sends_compressed_image_to_groq(self):
        response = Mock()
        response.json.return_value = {
            "choices": [
                {"message": {"content": "Открыт Telegram."}}
            ]
        }
        agent = PCAgent(
            api_key="test-key",
            vision_model="test-vision-model",
        )

        with (
            patch(
                "app.pc_agent.pyautogui.screenshot",
                return_value=Image.new("RGB", (1920, 1080)),
            ),
            patch(
                "app.pc_agent.requests.post",
                return_value=response,
            ) as post,
        ):
            result = agent.analyze_screen("Что открыто?")

        self.assertEqual(result, "Открыт Telegram.")
        request = post.call_args.kwargs
        self.assertEqual(
            request["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(
            request["json"]["model"],
            "test-vision-model",
        )
        image_url = request["json"]["messages"][1]["content"][1][
            "image_url"
        ]["url"]
        image_bytes = base64.b64decode(image_url.split(",", 1)[1])
        with Image.open(io.BytesIO(image_bytes)) as image:
            self.assertEqual(image.size, (1600, 900))

    def test_analyze_screen_requires_groq_key(self):
        agent = PCAgent()

        with patch("app.pc_agent.pyautogui.screenshot") as screenshot:
            result = agent.analyze_screen("Что открыто?")

        self.assertIn("API-ключ", result)
        screenshot.assert_not_called()

    def test_screen_tools_are_exposed_to_groq(self):
        agent = PCAgent()
        tool_names = {
            tool["function"]["name"]
            for tool in agent.get_tools()
        }

        self.assertTrue(
            {
                "analyze_screen",
                "screen_click",
                "screen_type",
                "screen_press",
                "screen_scroll",
                "screen_send",
            }.issubset(tool_names)
        )
        self.assertIn(
            "API-ключ",
            agent.execute_tool(
                "analyze_screen",
                {"question": "Что открыто?"},
            ),
        )

    def test_screen_navigation_click_does_not_prompt(self):
        agent = PCAgent()
        agent._confirm_screen_action = Mock()

        with (
            patch(
                "app.pc_agent.pyautogui.size",
                return_value=(800, 600),
            ),
            patch("app.pc_agent.pyautogui.click") as click,
        ):
            result = agent.screen_click(100, 100, "Открыть диалог")

        self.assertEqual(result, "Нажатие выполнено в точке (100, 100).")
        click.assert_called_once_with(100, 100)
        agent._confirm_screen_action.assert_not_called()

    def test_screen_send_requests_one_confirmation(self):
        agent = PCAgent()
        agent._confirm_screen_action = Mock(return_value=True)

        with (
            patch(
                "app.pc_agent.pyautogui.size",
                return_value=(800, 600),
            ),
            patch("app.pc_agent.pyautogui.click") as click,
        ):
            result = agent.screen_send(
                700,
                550,
                "Анна",
                "Привет!",
            )

        self.assertIn("Анна", result)
        agent._confirm_screen_action.assert_called_once()
        confirmation = agent._confirm_screen_action.call_args.args[0]
        self.assertIn("Привет!", confirmation)
        click.assert_called_once_with(700, 550)

    def test_cancelled_screen_send_does_not_click(self):
        agent = PCAgent()
        agent._confirm_screen_action = Mock(return_value=False)

        with (
            patch(
                "app.pc_agent.pyautogui.size",
                return_value=(800, 600),
            ),
            patch("app.pc_agent.pyautogui.click") as click,
        ):
            result = agent.screen_send(
                700,
                550,
                "Анна",
                "Привет!",
            )

        self.assertEqual(result, "__USER_CANCELLED__")
        click.assert_not_called()

    def test_screen_press_rejects_enter(self):
        agent = PCAgent()
        agent._confirm_screen_action = Mock()

        with patch("app.pc_agent.pyautogui.press") as press:
            result = agent.screen_press("enter", "Отправка сообщения")

        self.assertIn("screen_send", result)
        press.assert_not_called()
        agent._confirm_screen_action.assert_not_called()

    def test_screen_type_pastes_unicode_without_confirmation(self):
        agent = PCAgent()
        agent._confirm_screen_action = Mock()

        with (
            patch("app.pc_agent.pyperclip.paste", return_value="old"),
            patch("app.pc_agent.pyperclip.copy") as copy,
            patch("app.pc_agent.pyautogui.hotkey") as hotkey,
            patch("app.pc_agent.time.sleep"),
        ):
            result = agent.screen_type("Привет", "Поле сообщения")

        self.assertEqual(result, "Текст введён.")
        self.assertEqual(
            [call.args[0] for call in copy.call_args_list],
            ["Привет", "old"],
        )
        hotkey.assert_called_once_with("ctrl", "v")
        agent._confirm_screen_action.assert_not_called()

    def test_llm_stops_after_user_cancels_action(self):
        client = LLMClient(api_key="test-key")
        client._request = Mock(
            return_value={
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "screen_click",
                            "arguments": '{"x": 1, "y": 2, "reason": "test"}',
                        },
                    }
                ]
            }
        )

        result = client.ask_with_tools(
            prompt="Нажми кнопку",
            system="",
            tools=[],
            tool_executor=Mock(return_value="__USER_CANCELLED__"),
        )

        self.assertEqual(result, "Действие отменено пользователем.")
        client._request.assert_called_once()

    def test_chat_message_uses_assistant_command_queue(self):
        command_queue = queue.Queue()

        with patch.object(
            assistant_main,
            "_COMMAND_QUEUE",
            command_queue,
        ):
            assistant_main.submit_chat_message("  Скажи время  ")
            assistant_main.submit_chat_message(" ")

        self.assertEqual(
            command_queue.get_nowait(),
            ("chat", "Скажи время", "tasks"),
        )
        self.assertTrue(command_queue.empty())

    def test_command_catalog_includes_tools_and_local_commands(self):
        catalog = assistant_main.get_command_catalog(PCAgent())
        names = {
            item["function"]["name"]
            for item in catalog
        }

        self.assertIn("screen_send", names)
        self.assertIn("unit_convert", names)
        self.assertIn("doctor_check", names)
        self.assertIn("local_time", names)
        self.assertIn("local_date", names)
        self.assertIn("exit_assistant", names)


if __name__ == "__main__":
    unittest.main()
