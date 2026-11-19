import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.main import process_command
from app.pc_agent import PCAgent


class DirectApplicationCommandTests(unittest.TestCase):

    def setUp(self):
        self.agent = PCAgent()

    def test_open_variants_route_to_youtube(self):
        with patch.object(
            self.agent,
            "open_youtube",
            return_value="Открыл YouTube.",
        ) as open_youtube:
            for phrase in (
                "открой ютуб",
                "открыть ютуб",
                "открой youtube",
                "запустить youtube",
            ):
                with self.subTest(phrase=phrase):
                    self.assertEqual(
                        self.agent.handle(phrase),
                        "Открыл YouTube.",
                    )

        self.assertEqual(open_youtube.call_count, 4)

    def test_open_variants_route_to_telegram(self):
        with patch.object(
            self.agent,
            "open_app",
            return_value="Открыл Telegram.",
        ) as open_app:
            for phrase in (
                "открой телеграм",
                "открыть телеграм",
                "запусти telegram",
                "запустить telegram",
            ):
                with self.subTest(phrase=phrase):
                    self.assertEqual(
                        self.agent.handle(phrase),
                        "Открыл Telegram.",
                    )

        self.assertEqual(open_app.call_count, 4)
        self.assertTrue(
            all(call.args == ("telegram",) for call in open_app.call_args_list)
        )

    def test_open_variants_route_to_browser(self):
        with patch.object(
            self.agent,
            "open_app",
            return_value="Открыл браузер.",
        ) as open_app:
            for phrase in ("открой браузер", "открыть browser"):
                with self.subTest(phrase=phrase):
                    self.assertEqual(
                        self.agent.handle(phrase),
                        "Открыл браузер.",
                    )

        self.assertEqual(open_app.call_count, 2)
        self.assertTrue(
            all(call.args == ("browser",) for call in open_app.call_args_list)
        )

    def test_open_youtube_reports_browser_failure(self):
        with patch("app.pc_agent.open_url", return_value=False):
            self.assertIn("не удалось", self.agent.open_youtube().lower())

    def test_open_website_by_alias(self):
        with patch("app.pc_agent.open_url", return_value=True) as open_url:
            result = self.agent.handle("открой вконтакте")

        self.assertIn("https://vk.com", result)
        open_url.assert_called_once_with(
            "https://vk.com",
            window_titles=["вконтакте"],
        )

    def test_open_website_by_domain(self):
        with patch("app.pc_agent.open_url", return_value=True) as open_url:
            result = self.agent.handle("открой сайт example.com")

        self.assertIn("https://example.com", result)
        open_url.assert_called_once_with(
            "https://example.com",
            window_titles=["example.com"],
        )

    def test_open_app_uses_robust_launcher(self):
        with patch(
            "app.pc_agent.launch_by_name",
            return_value="Запущено: msedge.exe",
        ) as launch_by_name:
            result = self.agent.handle("открой edge")

        self.assertEqual(result, "Запущено: msedge.exe")
        launch_by_name.assert_called_once_with("msedge")

    def test_unknown_app_falls_through_to_llm(self):
        self.assertIsNone(self.agent.handle("открой мой файл"))

    def test_store_app_launcher_is_used_by_generic_tool(self):
        with patch(
            "app.tools.apps.launch_store_app",
            return_value="Запущено Telegram",
        ) as launch_store_app:
            result = self.agent.registry.execute(
                "app_launch",
                {"name": "telegram"},
            )

        self.assertEqual(result, "Запущено Telegram")
        launch_store_app.assert_called_once_with("Telegram")

    @patch("app.tools.apps.os.startfile")
    def test_protocol_alias_uses_windows_shell(self, startfile):
        result = self.agent.registry.execute(
            "app_launch",
            {"name": "discord"},
        )

        self.assertEqual(result, "Открыто: discord://")
        startfile.assert_called_once_with("discord://")

    @patch("app.main.publish_ui_event")
    @patch("app.main.handle_command", return_value=None)
    @patch("app.main.tracer")
    def test_direct_commands_are_dispatched_in_code_mode(
        self,
        tracer,
        _handle_command,
        _publish_ui_event,
    ):
        trace = tracer.return_value.start.return_value
        pc_agent = Mock()
        pc_agent.handle.return_value = "Открыл YouTube."

        process_command(
            text="открыть ютуб",
            tts=None,
            pc_agent=pc_agent,
            llm=SimpleNamespace(use_llm=False),
            persona_config={"address": "сэр"},
            speak_output=False,
            mode="code",
        )

        pc_agent.handle.assert_called_once_with("открыть ютуб")
        trace.finish.assert_called_once()
        _handle_command.assert_called_once_with(
            "открыть ютуб",
            memory=None,
        )
        self.assertTrue(
            any(
                call.args[0] == "assistant"
                for call in _publish_ui_event.call_args_list
            )
        )

    @patch("app.main.publish_ui_event")
    @patch("app.main.handle_command", return_value=None)
    @patch("app.main.tracer")
    def test_chat_mode_keeps_computer_commands_disabled(
        self,
        _tracer,
        _handle_command,
        _publish_ui_event,
    ):
        pc_agent = Mock()
        process_command(
            text="открыть ютуб",
            tts=None,
            pc_agent=pc_agent,
            llm=SimpleNamespace(use_llm=False),
            persona_config={"address": "сэр"},
            speak_output=False,
            mode="chat",
        )

        pc_agent.handle.assert_not_called()
        _handle_command.assert_not_called()
        _publish_ui_event.assert_any_call(
            "assistant",
            "Не удалось обработать команду. Языковая модель "
            "отключена. Проверьте DEEPSEEK_API_KEY в .env.",
        )
        _tracer.return_value.start.return_value.finish.assert_called_once()

    @patch("app.tools.apps.activate_window")
    @patch("app.tools.apps.os.startfile", side_effect=OSError)
    @patch("app.tools.apps._appx_executable", return_value=None)
    @patch("app.pc_agent.subprocess.Popen")
    @patch("app.pc_agent.subprocess.run")
    def test_telegram_store_app_is_launched(
        self,
        run,
        popen,
        _appx_executable,
        _startfile,
        activate_window,
    ):
        app_id = (
            "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!"
            "Telegram.TelegramDesktop.Store"
        )
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=app_id,
            stderr="",
        )

        result = self.agent.open_app("telegram")

        self.assertIn("Telegram", result)
        run.assert_called_once()
        popen.assert_called_once_with(
            ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
            cwd=None,
        )

    @patch("app.tools.apps.activate_window")
    @patch("app.tools.apps.os.startfile")
    @patch(
        "app.tools.apps._appx_executable",
        return_value=r"C:\Program Files\WindowsApps\Telegram\Telegram.exe",
    )
    def test_telegram_appx_executable_is_launched(
        self,
        _appx_executable,
        startfile,
        activate_window,
    ):
        result = self.agent.open_app("telegram")

        self.assertIn("Telegram", result)
        startfile.assert_called_once_with(
            r"C:\Program Files\WindowsApps\Telegram\Telegram.exe"
        )
        activate_window.assert_called_once_with(
            ["Telegram"],
            timeout=4.0,
            process_names=["Telegram"],
        )


class OpenUrlTests(unittest.TestCase):

    @patch("app.tools.common.activate_window")
    @patch("app.tools.common.subprocess.Popen")
    @patch(
        "app.tools.common._browser_executables",
        return_value=[r"C:\browser.exe"],
    )
    def test_open_url_launches_browser_explicitly(
        self,
        _browsers,
        popen,
        activate_window,
    ):
        from app.tools.common import open_url

        self.assertTrue(open_url("youtube.com"))
        popen.assert_called_once_with(
            [r"C:\browser.exe", "https://youtube.com"],
            close_fds=True,
        )
        activate_window.assert_called_once_with(
            ["youtube"],
            timeout=3.0,
        )

    @patch("app.tools.common.activate_window")
    @patch("app.tools.common.subprocess.Popen")
    @patch("app.tools.common._browser_executables", return_value=[])
    def test_open_url_falls_back_to_explorer(
        self,
        _browsers,
        popen,
        activate_window,
    ):
        from app.tools.common import open_url

        self.assertTrue(open_url("https://example.com"))
        popen.assert_called_once_with(
            ["explorer.exe", "https://example.com"]
        )
        activate_window.assert_called_once_with(
            ["example"],
            timeout=3.0,
        )


if __name__ == "__main__":
    unittest.main()