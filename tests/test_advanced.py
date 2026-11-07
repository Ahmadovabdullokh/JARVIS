import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.doctor import format_report, run_checks
from app.llm_client import LLMClient
from app.rag import RagIndex
from app.safety import SafetyManager
from app.sessions import SessionStore
from app.tasks import TaskManager
from app.tools import productivity, screen
from app.tools.base import ToolRegistry, ToolResult, ToolSpec
from app.undo import UndoJournal


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok_response(content="ok"):
    return FakeResponse(
        200,
        {"choices": [{"message": {"content": content}}]},
    )


class UndoTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.journal = UndoJournal(
            path=self.root / "journal.jsonl",
            backup_dir=self.root / "backups",
        )

    def tearDown(self):
        self.folder.cleanup()

    def test_undo_write_restores_previous_version(self):
        path = self.root / "note.txt"
        path.write_text("old", encoding="utf-8")
        self.journal.record_write(path)
        path.write_text("new", encoding="utf-8")
        self.assertIn("Восстановлена", self.journal.undo_last())
        self.assertEqual(path.read_text(encoding="utf-8"), "old")

    def test_undo_created_removes_file(self):
        path = self.root / "created.txt"
        self.journal.record_created(path)
        path.write_text("x", encoding="utf-8")
        self.journal.undo_last()
        self.assertFalse(path.exists())

    def test_undo_delete_restores_file(self):
        path = self.root / "deleted.txt"
        path.write_text("data", encoding="utf-8")
        self.journal.record_delete(path)
        self.assertFalse(path.exists())
        self.journal.undo_last()
        self.assertEqual(path.read_text(encoding="utf-8"), "data")

    def test_undo_move_returns_source(self):
        source = self.root / "source.txt"
        destination = self.root / "destination.txt"
        source.write_text("data", encoding="utf-8")
        self.journal.record_move(source, destination)
        source.rename(destination)
        self.journal.undo_last()
        self.assertTrue(source.exists())
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "data")


class SessionStoreTests(unittest.TestCase):

    def test_messages_and_search(self):
        with TemporaryDirectory() as folder:
            store = SessionStore(Path(folder) / "sessions.db")
            session = store.create_session("Тест")
            store.add_message(session, "user", "привет")
            store.add_message(session, "assistant", "здравствуйте")
            history = store.history(session)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["role"], "user")
            self.assertTrue(store.search("здравствуйте"))
            self.assertEqual(store.latest_session_id(), session)
            store.close()


class ToolResultTests(unittest.TestCase):

    def test_result_and_cancellation(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="bad",
                description="bad",
                parameters={"type": "object"},
                handler=lambda **_: ToolResult(
                    status="error",
                    text="bad result",
                ),
            )
        )
        result = registry.execute_result("bad", {})
        self.assertEqual(result.status, "error")
        self.assertEqual(registry.execute("bad", {}), "bad result")

        event = threading.Event()
        event.set()
        registry.context.cancel_event = event
        cancelled = registry.execute_result("bad", {})
        self.assertEqual(cancelled.status, "cancelled")


class SafetyPolicyTests(unittest.TestCase):

    def _spec(self, name="demo", danger="dangerous"):
        return ToolSpec(
            name=name,
            description="demo",
            parameters={"type": "object"},
            handler=lambda: "ok",
            danger=danger,
        )

    def test_deny_policy(self):
        safety = SafetyManager(
            {"safety": {"tool_policies": {"demo": "deny"}}}
        )
        verdict = safety.before_tool(self._spec(), {})
        self.assertIn("запрещён", verdict)

    def test_taint_forces_confirmation(self):
        safety = SafetyManager(
            {"safety": {"autonomy": "full", "taint_tracking": True}}
        )
        calls = []

        def handler(action, reason, prompt):
            calls.append((action, reason, prompt))
            return False

        safety.set_confirm_handler(handler)
        safety.mark_untrusted("web_search")
        verdict = safety.before_tool(self._spec(), {})
        self.assertFalse(verdict)
        self.assertEqual(len(calls), 1)
        self.assertIn("недоверенный", calls[0][1])

    def test_audit_rotates(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "audit.log"
            safety = SafetyManager(
                {
                    "safety": {
                        "audit_log": str(path),
                        "audit_max_bytes": 200,
                    }
                }
            )
            for index in range(10):
                safety._audit(event="test", index=index)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_suffix(".log.1").exists())

    def test_redacts_key_value_secrets(self):
        safety = SafetyManager()
        text = '{"password": "secret123", "api_key": "abc"}'
        redacted = safety.redact(text)
        self.assertNotIn("secret123", redacted)
        self.assertNotIn('"abc"', redacted)
        self.assertIn("***", redacted)

    def test_session_allow_bypasses_taint(self):
        safety = SafetyManager(
            {"safety": {"autonomy": "full", "taint_tracking": True}}
        )
        safety.set_confirm_handler(lambda *_: False)
        safety.mark_untrusted("web_search")
        safety.allow_session("demo")
        self.assertTrue(safety.before_tool(self._spec(), {}))


class LLMClientTests(unittest.TestCase):

    def test_retry_then_success(self):
        client = LLMClient(
            api_key="test",
            max_retries=1,
            retry_backoff=0,
        )
        responses = [FakeResponse(500, {}), ok_response("hello")]
        with patch(
            "app.llm_client.requests.post",
            side_effect=responses,
        ) as post:
            message = client._request({"model": "x"})
        self.assertEqual(message["content"], "hello")
        self.assertEqual(post.call_count, 2)

    def test_payload_too_large_reduces_tool_result_and_retries(self):
        client = LLMClient(api_key="test", max_retries=0)
        tool_result = "строка результата " * 1000
        payload = {
            "model": "x",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "tool", "content": tool_result},
                {"role": "user", "content": "объясни"},
            ],
            "max_tokens": 3000,
        }
        responses = [
            FakeResponse(413, {"error": {"message": "too large"}}),
            ok_response("готово"),
        ]

        with patch(
            "app.llm_client.requests.post",
            side_effect=responses,
        ) as post:
            message = client._request(payload)

        self.assertEqual(message["content"], "готово")
        self.assertEqual(post.call_count, 2)
        sent_payload = post.call_args_list[1][1]["json"]
        self.assertLess(
            len(sent_payload["messages"][1]["content"]),
            len(tool_result),
        )
        self.assertLess(sent_payload["max_tokens"], 3000)

    def test_fallback_endpoint(self):
        client = LLMClient(
            api_key="test",
            max_retries=0,
            fallback_base_url="http://fallback/v1/chat",
            fallback_model="fallback-model",
            fallback_api_key="fallback-key",
        )
        responses = [FakeResponse(503, {}), ok_response("fallback")]
        with patch(
            "app.llm_client.requests.post",
            side_effect=responses,
        ) as post:
            message = client._request({"model": "x"})
        self.assertEqual(message["content"], "fallback")
        self.assertEqual(post.call_count, 2)

    def test_session_history_is_loaded_and_saved(self):
        with TemporaryDirectory() as folder:
            store = SessionStore(Path(folder) / "sessions.db")
            session = store.create_session("Тест")
            store.add_message(session, "user", "старый вопрос")
            store.add_message(session, "assistant", "старый ответ")
            client = LLMClient(
                api_key="test",
                session_store=store,
                session_id=session,
            )
            self.assertEqual(client.history[0]["content"], "старый вопрос")
            client._append_history("новый вопрос", "новый ответ")
            messages = store.messages(session)
            self.assertEqual(messages[-1]["content"], "новый ответ")
            store.close()

    def test_untrusted_result_is_wrapped(self):
        client = LLMClient(api_key="test")
        wrapped = client._wrap_untrusted("web_search", "данные")
        self.assertIn("<untrusted_content", wrapped)
        self.assertIn("данные", wrapped)
        plain = client._wrap_untrusted("dev_hash", "данные")
        self.assertEqual(plain, "данные")

    def test_tool_steps_are_saved_in_task(self):
        with TemporaryDirectory() as folder:
            tasks = TaskManager(path=Path(folder) / "tasks.json")
            task_id = tasks.create("Тест")
            tasks.start(task_id)
            client = LLMClient(api_key="test")
            client._request = Mock(
                side_effect=[
                    {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "demo",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    },
                    {"content": "готово"},
                ]
            )
            answer = client.ask_with_tools(
                prompt="сделай",
                system="",
                tools=[],
                tool_executor=lambda *_: "результат",
                task_manager=tasks,
                task_id=task_id,
            )
            self.assertEqual(answer, "готово")
            task = tasks.get(task_id)
            self.assertTrue(
                any("demo" in step["title"] for step in task["steps"])
            )


class RagTests(unittest.TestCase):

    def test_index_and_search(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "docs"
            root.mkdir()
            (root / "cats.txt").write_text(
                "кошка сидит на окне",
                encoding="utf-8",
            )
            (root / "dogs.txt").write_text(
                "собака бежит по парку",
                encoding="utf-8",
            )
            rag = RagIndex(Path(folder) / "rag.db")
            report = rag.index(root)
            self.assertIn("файлов: 2", report)
            results = rag.search("кошка")
            self.assertTrue(results)
            self.assertIn("cats.txt", results[0]["source"])
            self.assertEqual(rag.stats()["files"], 2)
            rag.clear()
            self.assertFalse(rag.search("кошка"))
            rag.close()

    def test_index_docx(self):
        try:
            from docx import Document
        except Exception:
            self.skipTest("python-docx не установлен")
        with TemporaryDirectory() as folder:
            root = Path(folder) / "docs"
            root.mkdir()
            document = Document()
            document.add_paragraph("уникальное слово кварц")
            document.save(str(root / "doc.docx"))
            rag = RagIndex(Path(folder) / "rag.db")
            rag.index(root)
            results = rag.search("кварц")
            self.assertTrue(results)
            self.assertIn("doc.docx", results[0]["source"])
            rag.close()


class ObservabilityTests(unittest.TestCase):

    def test_trace_roundtrip(self):
        from app.observability import TraceLogger

        with TemporaryDirectory() as folder:
            logger = TraceLogger(Path(folder) / "traces.jsonl")
            trace = logger.start("проверка", source="voice", mode="code")
            trace.tool("demo", {"x": 1}, "ok", 0.1)
            trace.finish("готово")
            tail = logger.tail()
            self.assertIn(trace.id, tail)
            self.assertIn("demo", tail)
            self.assertIn('"mode": "code"', tail)
            self.assertIn('"source": "voice"', tail)
            logger.clear()
            self.assertIn("пуст", logger.tail().lower())


class DoctorTests(unittest.TestCase):

    def test_configs_are_valid_json(self):
        root = Path(__file__).resolve().parent.parent
        names = ["config.example.json"]
        if (root / "config" / "config.json").exists():
            names.append("config.json")
        for name in names:
            data = json.loads(
                (root / "config" / name).read_text(encoding="utf-8")
            )
            self.assertIn("agent", data)
            self.assertIn("safety", data)
            self.assertIn("llm", data)

    def test_doctor_report_has_expected_sections(self):
        checks = run_checks()
        names = {item["name"] for item in checks}
        self.assertIn("Python", names)
        self.assertIn("Tesseract OCR", names)
        report = format_report(checks)
        self.assertIn("JARVIS DIAGNOSTICS", report)
        self.assertIn("Итог:", report)


class NewToolTests(unittest.TestCase):

    def test_contacts_roundtrip(self):
        with TemporaryDirectory() as folder:
            old = productivity.DATA_DIR
            productivity.DATA_DIR = Path(folder)
            try:
                registry = ToolRegistry()
                productivity.register(registry)
                registry.execute(
                    "contacts_add",
                    {"name": "Алиса", "value": "+123", "kind": "phone"},
                )
                result = registry.execute(
                    "contacts_search",
                    {"query": "алиса"},
                )
                self.assertIn("+123", result)
            finally:
                productivity.DATA_DIR = old

    def test_calendar_ics_roundtrip(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "calendar.ics"
            start = time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(time.time() + 86400),
            )
            registry = ToolRegistry()
            productivity.register(registry)
            created = registry.execute(
                "calendar_create_ics",
                {
                    "path": str(path),
                    "title": "Встреча",
                    "start": start,
                },
            )
            self.assertIn("создано", created.lower())
            result = registry.execute(
                "calendar_read_ics",
                {"path": str(path), "days": 10},
            )
            self.assertIn("Встреча", result)

    def test_screen_click_text_without_tesseract(self):
        registry = ToolRegistry()
        with patch("app.tools.screen.optional_import", return_value=None):
            screen.register(registry)
            result = registry.execute(
                "screen_click_text",
                {"text": "OK"},
            )
        self.assertIn("pytesseract", result)

    def test_screen_click_text_clicks_matched_word(self):
        registry = ToolRegistry()
        fake_tesseract = SimpleNamespace(
            Output=SimpleNamespace(DICT="dict"),
            image_to_data=lambda *args, **kwargs: {
                "text": ["OK"],
                "conf": ["90"],
                "left": [10],
                "top": [20],
                "width": [30],
                "height": [10],
            },
        )
        with (
            patch(
                "app.tools.screen.optional_import",
                return_value=fake_tesseract,
            ),
            patch("app.tools.screen._grab", return_value=object()),
            patch("app.tools.screen.pyautogui.click") as click,
        ):
            screen.register(registry)
            result = registry.execute(
                "screen_click_text",
                {"text": "OK"},
            )
        self.assertIn("Нажатие", result)
        click.assert_called_once_with(
            25,
            25,
            clicks=1,
            button="left",
        )


if __name__ == "__main__":
    unittest.main()
