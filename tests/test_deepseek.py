import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import main as assistant_main
from app.llm_client import LLMClient
from app.pc_agent import PCAgent
from app.utils import safe_print


class DeepSeekProviderTests(unittest.TestCase):

    def test_deepseek_is_default_provider(self):
        client = LLMClient(api_key="test-key", use_llm=True)
        self.assertEqual(client.provider, "deepseek")
        self.assertEqual(
            client.api_url,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(client.model, "deepseek-chat")
        self.assertTrue(client.api_key)

    def test_provider_alias_and_custom_base_url(self):
        client = LLMClient(
            api_key="test-key",
            provider="deep-seek",
            base_url="http://localhost/deepseek",
            model="deepseek-chat",
        )
        self.assertEqual(client.provider, "deepseek")
        self.assertEqual(client.api_url, "http://localhost/deepseek")

    def test_tool_payload_omits_parallel_flag_when_disabled(self):
        client = LLMClient(api_key="test-key")
        payloads = []

        def fake_request(payload, api_url=None, api_key=None):
            payloads.append(payload)
            return {"content": "готово"}

        with patch.object(client, "_request", fake_request):
            client.ask_with_tools(
                prompt="проверь проект",
                system="",
                tools=[{"type": "function", "function": {"name": "x"}}],
                tool_executor=lambda *_: "ok",
            )

        self.assertEqual(payloads[0]["model"], "deepseek-chat")
        self.assertNotIn("parallel_tool_calls", payloads[0])
        self.assertEqual(payloads[0]["tool_choice"], "auto")


class DeepSeekConfigTests(unittest.TestCase):

    def test_env_key_and_default_model(self):
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "env-deepseek-key"},
            clear=False,
        ):
            config = assistant_main.get_llm_config(
                {"llm": {"provider": "deepseek"}}
            )

        self.assertEqual(config["provider"], "deepseek")
        self.assertEqual(config["api_key"], "env-deepseek-key")
        self.assertEqual(config["model"], "deepseek-chat")

    def test_llm_section_overrides_env(self):
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "env-key"},
            clear=False,
        ):
            config = assistant_main.get_llm_config(
                {
                    "llm": {
                        "provider": "deepseek",
                        "api_key": "config-key",
                        "model": "deepseek-reasoner",
                    }
                }
            )

        self.assertEqual(config["api_key"], "config-key")
        self.assertEqual(config["model"], "deepseek-reasoner")

    def test_groq_provider_keeps_groq_model(self):
        with patch.dict(
            os.environ,
            {"GROQ_API_KEY": "groq-key"},
            clear=False,
        ):
            config = assistant_main.get_llm_config(
                {
                    "llm": {
                        "provider": "groq",
                        "model": "openai/gpt-oss-120b",
                    }
                }
            )

        self.assertEqual(config["provider"], "groq")
        self.assertEqual(config["api_key"], "groq-key")
        self.assertEqual(config["model"], "openai/gpt-oss-120b")


class SafePrintTests(unittest.TestCase):

    def test_unencodable_answer_does_not_break_message_sending(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(
            buffer,
            encoding="cp1251",
            errors="strict",
        )

        safe_print("ответ\u202fс\u00a0символами", file=stream)
        stream.flush()

        self.assertIn(b"\xee\xf2\xe2\xe5\xf2", buffer.getvalue())


class CodeToolsetTests(unittest.TestCase):

    def test_code_toolset_is_compact_and_relevant(self):
        agent = PCAgent()
        tools = agent.get_code_llm_tools(
            "исправь ошибку в PythonProject9"
        )
        names = {
            tool["function"]["name"] for tool in tools
        }

        self.assertLessEqual(len(tools), 28)
        self.assertIn("code_tree", names)
        self.assertIn("code_project_snapshot", names)
        self.assertIn("code_read", names)
        self.assertIn("code_read_many", names)
        self.assertIn("code_write", names)
        self.assertIn("code_edit", names)
        self.assertIn("code_multi_edit", names)
        self.assertIn("code_test", names)
        self.assertIn("run_powershell", names)
        self.assertIn("run_capability", names)

    def test_visual_query_adds_gui_tools(self):
        agent = PCAgent()
        tools = agent.get_code_llm_tools(
            "открой VS Code и проверь экран"
        )
        names = {
            tool["function"]["name"] for tool in tools
        }

        self.assertIn("automation_copilot_fix", names)
        self.assertIn("screen_ocr", names)
        self.assertLessEqual(len(tools), 28)


class CodeToolTests(unittest.TestCase):

    def test_env_file_overrides_stale_process_key(self):
        with patch("app.main.load_dotenv") as loader:
            assistant_main.load_config()

        self.assertTrue(loader.call_args.kwargs.get("override"))

    def test_project_name_resolves_next_to_configured_project(self):
        with TemporaryDirectory() as folder:
            parent = Path(folder)
            first = parent / "PythonProject9"
            second = parent / "PythonProject10"
            first.mkdir()
            second.mkdir()
            (second / "main.py").write_text("x = 1\n", encoding="utf-8")
            agent = PCAgent(
                config={"code": {"project": str(first)}}
            )

            tree = agent.execute_tool(
                "code_tree",
                {"project": "PythonProject10"},
            )
            self.assertIn("main.py", tree)

    def test_code_edit_and_read_roundtrip(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "main.py"
            target.write_text("print('old')\n", encoding="utf-8")
            agent = PCAgent(config={"code": {"project": folder}})

            result = agent.execute_tool(
                "code_edit",
                {
                    "path": "main.py",
                    "old_string": "old",
                    "new_string": "new",
                },
            )
            self.assertIn("Изменено", result)
            self.assertIn("new", target.read_text(encoding="utf-8"))

            read = agent.execute_tool(
                "code_read",
                {"path": "main.py"},
            )
            self.assertIn("1 | print('new')", read)

    def test_code_tree_and_project_info(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app").mkdir()
            (root / "app" / "main.py").write_text(
                "def run():\n    return 1\n",
                encoding="utf-8",
            )
            agent = PCAgent(config={"code": {"project": folder}})

            tree = agent.execute_tool("code_tree", {})
            info = agent.execute_tool("code_project_info", {})
            symbols = agent.execute_tool("code_symbols", {})

            self.assertIn("app/", tree)
            self.assertIn("Файлов:", info)
            self.assertIn("def run", symbols)


class ContextCompactionTests(unittest.TestCase):

    def test_old_tool_results_are_compacted(self):
        messages = [
            {"role": "tool", "content": "x" * 6000},
            {"role": "tool", "content": "y" * 6000},
            {"role": "tool", "content": "z" * 6000},
        ]

        LLMClient._compact_tool_messages(messages, max_chars=10000)

        total = sum(
            len(message["content"])
            for message in messages
        )
        self.assertLess(total, 18000)
        self.assertIn("старый результат", messages[0]["content"])

    def test_429_error_is_short_and_human_readable(self):
        summary = LLMClient._error_summary(
            429,
            '{"error": {"message": "rate limit ..."}}',
        )
        self.assertIn("лимит", summary)
        self.assertNotIn("organization", summary)


class CodeBackendTests(unittest.TestCase):

    def test_deepseek_backend_skips_copilot(self):
        config = {"code": {"backend": "deepseek"}}
        self.assertEqual(
            assistant_main.get_code_backend(config),
            "deepseek",
        )
        self.assertFalse(
            assistant_main.code_backend_uses_copilot(config)
        )

    def test_auto_backend_can_use_copilot(self):
        config = {"code": {"backend": "auto"}}
        self.assertTrue(
            assistant_main.code_backend_uses_copilot(config)
        )

    def test_unknown_backend_falls_back_to_deepseek(self):
        config = {"code": {"backend": "неизвестно"}}
        self.assertEqual(
            assistant_main.get_code_backend(config),
            "deepseek",
        )


if __name__ == "__main__":
    unittest.main()
