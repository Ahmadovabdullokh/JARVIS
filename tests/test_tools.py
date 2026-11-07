import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.pc_agent import PCAgent
from app.safety import SafetyManager
from app.tasks import TaskManager
from app.tools import load_report, register_all_tools
from app.tools.base import ToolRegistry, ToolSpec


class ToolRegistryTests(unittest.TestCase):

    def setUp(self):
        self.registry = ToolRegistry()
        self.loaded, self.errors = register_all_tools(self.registry)

    def test_all_tool_modules_load(self):
        self.assertEqual(self.errors, [], load_report())
        self.assertGreaterEqual(len(self.loaded), 22)
        self.assertGreaterEqual(len(self.registry.all()), 370)

    def test_tool_names_are_unique(self):
        names = [tool.name for tool in self.registry.all()]
        self.assertEqual(len(names), len(set(names)))

    def test_catalog_and_schema(self):
        catalog = self.registry.catalog(query="конвертировать единицы")
        names = {item["name"] for item in catalog}
        self.assertIn("unit_convert", names)
        schema = self.registry.schemas(names=["unit_convert"])
        self.assertEqual(len(schema), 1)
        self.assertEqual(schema[0]["type"], "function")

    def test_argument_validation(self):
        result = self.registry.execute(
            "unit_convert",
            {"value": "один", "from": "km", "to": "m"},
        )
        self.assertIn("должен иметь тип", result)

    def test_safe_tools_execute(self):
        self.assertEqual(
            self.registry.execute(
                "unit_convert",
                {"value": 1, "from": "km", "to": "m"},
            ),
            "1 km = 1000 m",
        )
        self.assertEqual(
            self.registry.execute("dev_hash", {"text": "hello"}),
            hashlib.sha256(b"hello").hexdigest(),
        )
        random_value = int(
            self.registry.execute("secure_random", {"min": 5, "max": 6})
        )
        self.assertEqual(random_value, 5)

    def test_file_tools_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "note.txt"
            written = self.registry.execute(
                "file_write",
                {"path": str(path), "content": "привет"},
            )
            self.assertIn("записан", written.lower())
            self.assertEqual(
                self.registry.execute("file_read", {"path": str(path)}),
                "привет",
            )
            info = self.registry.execute(
                "file_info", {"path": str(path)}
            )
            self.assertIn("note.txt", info)

    def test_office_tools_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            docx_path = folder / "doc.docx"
            self.registry.execute(
                "docx_create",
                {
                    "path": str(docx_path),
                    "title": "Заголовок",
                    "text": "Текст",
                },
            )
            self.assertIn(
                "Текст",
                self.registry.execute(
                    "docx_read", {"path": str(docx_path)}
                ),
            )

            xlsx_path = folder / "book.xlsx"
            self.registry.execute(
                "xlsx_create",
                {
                    "path": str(xlsx_path),
                    "rows": [["a", "b"], [1, 2]],
                },
            )
            self.assertIn(
                "a | b",
                self.registry.execute(
                    "xlsx_read", {"path": str(xlsx_path)}
                ),
            )

            pdf_path = folder / "doc.pdf"
            self.registry.execute(
                "pdf_create",
                {"path": str(pdf_path), "text": "PDF text"},
            )
            self.assertIn(
                "PDF text",
                self.registry.execute(
                    "pdf_read", {"path": str(pdf_path)}
                ),
            )

    def test_security_roundtrip(self):
        encrypted = self.registry.execute(
            "text_encrypt",
            {"text": "секрет", "password": "пароль"},
        )
        self.assertNotIn("секрет", encrypted)
        self.assertEqual(
            self.registry.execute(
                "text_decrypt",
                {"token": encrypted, "password": "пароль"},
            ),
            "секрет",
        )

    def test_qr_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qr.png"
            self.registry.execute(
                "qr_generate",
                {"text": "https://example.com", "path": str(path)},
            )
            self.assertTrue(path.exists())
            self.assertIn(
                "example.com",
                self.registry.execute("qr_read", {"path": str(path)}),
            )


class SafetyTests(unittest.TestCase):

    def test_full_autonomy_allows_tools_and_audits(self):
        with tempfile.TemporaryDirectory() as folder:
            safety = SafetyManager(
                {
                    "safety": {
                        "autonomy": "full",
                        "confirm_destructive": False,
                        "audit_log": str(Path(folder) / "audit.log"),
                    }
                }
            )
            spec = ToolSpec(
                name="demo",
                description="demo",
                parameters={"type": "object"},
                handler=lambda: "ok",
                danger="dangerous",
            )
            self.assertTrue(safety.before_tool(spec, {}))
            result = safety.after_tool(spec, {}, "x" * 100, 0.1)
            self.assertTrue(result)
            self.assertIn("demo", safety.tail_audit())

    def test_dry_run_does_not_execute(self):
        safety = SafetyManager(
            {"safety": {"autonomy": "full", "dry_run": True}}
        )
        spec = ToolSpec(
            name="demo",
            description="demo",
            parameters={"type": "object"},
            handler=lambda: "ok",
            danger="confirm",
        )
        verdict = safety.before_tool(spec, {"path": "x"})
        self.assertIsInstance(verdict, str)
        self.assertIn("DRY-RUN", verdict)

    def test_stop_blocks_execution(self):
        safety = SafetyManager()
        safety.stop()
        spec = ToolSpec(
            name="demo",
            description="demo",
            parameters={"type": "object"},
            handler=lambda: "ok",
        )
        self.assertIn("остановлено", safety.before_tool(spec, {}).lower())


class TaskManagerTests(unittest.TestCase):

    def test_task_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = TaskManager(path=Path(folder) / "tasks.json")
            task_id = manager.create("Тест")
            manager.add_step(task_id, "Шаг")
            manager.start(task_id)
            manager.complete(task_id, "Готово")
            task = manager.get(task_id)
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["result"], "Готово")
            self.assertEqual(len(task["steps"]), 1)


class PCAgentToolTests(unittest.TestCase):

    def test_extended_tool_is_executable(self):
        agent = PCAgent()
        self.assertEqual(
            agent.execute_tool("dev_hash", {"text": "hello"}),
            hashlib.sha256(b"hello").hexdigest(),
        )

    def test_llm_tools_include_legacy_and_extended(self):
        agent = PCAgent()
        tools = agent.get_llm_tools("конвертировать единицы измерения")
        self.assertLessEqual(len(tools), 80)
        names = {tool["function"]["name"] for tool in tools}
        self.assertIn("system_status", names)
        self.assertIn("run_powershell", names)
        self.assertIn("list_capabilities", names)
        self.assertIn("unit_convert", names)

    def test_russian_query_selects_relevant_tools(self):
        agent = PCAgent()
        names = {
            tool["function"]["name"]
            for tool in agent.get_llm_tools(
                "создай документ Word и отправь на почту"
            )
        }
        self.assertIn("docx_create", names)
        self.assertIn("email_send", names)

    def test_registry_status_reports_loaded_modules(self):
        agent = PCAgent()
        self.assertIn("Инструментов в реестре", agent.get_registry_status())

    def test_disabled_tools_are_hidden(self):
        agent = PCAgent(
            config={
                "agent": {},
                "tools": {"disabled_tools": ["dev_hash"]},
            }
        )
        self.assertFalse(agent.registry.get("dev_hash").enabled)
        self.assertIn(
            "отключён",
            agent.execute_tool("dev_hash", {"text": "x"}),
        )
        catalog = agent.registry.catalog(query="hash")
        self.assertNotIn(
            "dev_hash",
            {item["name"] for item in catalog},
        )

    def test_enabled_categories_filter_registry(self):
        agent = PCAgent(
            config={
                "agent": {},
                "tools": {"enabled_categories": ["files"]},
            }
        )
        enabled = [
            spec.category
            for spec in agent.registry.all()
            if spec.enabled
        ]
        self.assertTrue(enabled)
        self.assertEqual(set(enabled), {"files"})
        self.assertFalse(agent.registry.get("system_info").enabled)

    def test_disabled_legacy_tool_is_blocked(self):
        agent = PCAgent(
            config={
                "agent": {},
                "tools": {"disabled_tools": ["shutdown_pc"]},
            }
        )
        names = {
            tool["function"]["name"]
            for tool in agent.get_llm_tools("выключи компьютер")
        }
        self.assertNotIn("shutdown_pc", names)
        self.assertIn(
            "отключён",
            agent.execute_tool("shutdown_pc", {}),
        )

    def test_enabled_categories_filter_legacy_tools(self):
        agent = PCAgent(
            config={
                "agent": {},
                "tools": {"enabled_categories": ["files"]},
            }
        )
        names = {
            tool["function"]["name"]
            for tool in agent.get_llm_tools("найди файл")
        }
        self.assertIn("find_files", names)
        self.assertNotIn("shutdown_pc", names)
        self.assertNotIn("web_search", names)

    def test_tool_timeout_from_config(self):
        agent = PCAgent(
            config={
                "agent": {"tool_timeout_seconds": 7},
                "tools": {},
            }
        )
        self.assertEqual(agent.registry.get("dev_hash").timeout, 7.0)

    def test_legacy_tools_obey_safety(self):
        agent = PCAgent(
            config={
                "agent": {},
                "safety": {"dry_run": True},
            }
        )
        result = agent.execute_tool(
            "close_app",
            {"app_name": "notepad"},
        )
        self.assertIn("DRY-RUN", result)

        agent.safety.resume()
        agent.safety.stop()
        result = agent.execute_tool("system_status", {})
        self.assertIn("остановлено", result.lower())


class MemoryToolTests(unittest.TestCase):

    def test_memory_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            with patch(
                "app.tools.memory_tools.DEFAULT_PATH",
                path,
            ):
                registry = ToolRegistry()
                register_all_tools(registry)
                self.assertIn(
                    "Запомнено",
                    registry.execute(
                        "memory_remember",
                        {"fact": "тестовый факт"},
                    ),
                )
                self.assertIn(
                    "тестовый факт",
                    registry.execute("memory_facts", {}),
                )
                self.assertIn(
                    "тестовый факт",
                    registry.execute(
                        "memory_search",
                        {"query": "тестовый"},
                    ),
                )
                registry.execute(
                    "memory_profile_set",
                    {"key": "город", "value": "Москва"},
                )
                self.assertIn(
                    "Москва",
                    registry.execute(
                        "memory_profile_get",
                        {"key": "город"},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
