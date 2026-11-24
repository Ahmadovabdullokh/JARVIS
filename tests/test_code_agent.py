import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.code_state import CodeAgentState
from app.llm_client import LLMClient
from app.pc_agent import PCAgent
from app.safety import SafetyManager, redact_secrets
from app.tools.base import ToolSpec


class CodeAgentStateTests(unittest.TestCase):

    def test_plan_and_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            state = CodeAgentState(path=Path(folder) / "state.json")
            state.begin_task("исправь тест", folder)
            state.set_plan(["прочитать", "исправить", "проверить"])

            self.assertIn("[ ] прочитать", state.plan_text())
            self.assertIn("исправь тест", state.prompt())
            self.assertTrue(state.active)

    def test_checkpoint_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "a.py"
            target.write_text("old\n", encoding="utf-8")
            state = CodeAgentState(path=root / "state.json")
            state.begin_task("fix", str(root))
            backup = state.backup_file(target)
            target.write_text("new\n", encoding="utf-8")
            state.mark_changed(
                target,
                backup=backup.get("backup"),
                existed=True,
            )

            state.rollback()

            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertFalse(state.changed_files)

    def test_continuation_keeps_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            state = CodeAgentState(path=Path(folder) / "state.json")
            state.begin_task("первая задача", folder)
            state.set_plan(["шаг"])
            state.finish()

            state.begin_task("продолжай", folder)

            self.assertEqual(len(state.plan), 1)
            self.assertIn("продолжай", state.goal)


class CodeToolWorkflowTests(unittest.TestCase):

    def _agent(self, root):
        agent = PCAgent(
            config={
                "code": {
                    "project": str(root),
                    "verify_tests": False,
                }
            }
        )
        agent.code_state.begin_task("исправь", str(root))
        return agent

    def test_plan_and_read_are_required_before_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "main.py"
            target.write_text("print('old')\n", encoding="utf-8")
            agent = self._agent(root)

            blocked = agent.execute_tool(
                "code_edit",
                {
                    "path": "main.py",
                    "old_string": "old",
                    "new_string": "new",
                },
            )
            self.assertIn("code_plan", blocked)

            agent.execute_tool(
                "code_plan",
                {"steps": ["прочитать", "исправить", "проверить"]},
            )
            blocked = agent.execute_tool(
                "code_edit",
                {
                    "path": "main.py",
                    "old_string": "old",
                    "new_string": "new",
                },
            )
            self.assertIn("code_read", blocked)

            agent.execute_tool("code_read", {"path": "main.py"})
            result = agent.execute_tool(
                "code_edit",
                {
                    "path": "main.py",
                    "old_string": "old",
                    "new_string": "new",
                },
            )
            self.assertIn("Изменено", result)
            self.assertIn("print('new')", target.read_text(encoding="utf-8"))

            verify = agent.execute_tool("code_verify", {})
            self.assertIn("[OK]", verify)
            self.assertTrue(agent.code_state.verified)

    def test_multi_edit_is_transactional(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "a.py"
            second = root / "b.py"
            first.write_text("one\n", encoding="utf-8")
            second.write_text("two\n", encoding="utf-8")
            agent = self._agent(root)
            agent.execute_tool("code_plan", {"steps": ["edit"]})
            agent.execute_tool("code_read_many", {"paths": ["a.py", "b.py"]})

            result = agent.execute_tool(
                "code_multi_edit",
                {
                    "edits": [
                        {
                            "path": "a.py",
                            "old_string": "one",
                            "new_string": "ONE",
                        },
                        {
                            "path": "b.py",
                            "old_string": "missing",
                            "new_string": "TWO",
                        },
                    ]
                },
            )

            self.assertIn("Ничего не изменено", result)
            self.assertEqual(first.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "two\n")

    def test_outside_project_and_secrets_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root.parent / "outside.py"
            agent = self._agent(root)
            agent.execute_tool("code_plan", {"steps": ["write"]})

            blocked = agent.execute_tool(
                "code_write",
                {"path": str(outside), "content": "x = 1\n"},
            )
            self.assertIn("вне проекта", blocked)
            self.assertFalse(outside.exists())

            secret = "123456789:" + "A" * 35
            blocked = agent.execute_tool(
                "code_write",
                {"path": "secret.py", "content": f"TOKEN = '{secret}'\n"},
            )
            self.assertIn("секрет", blocked)


class CodeLoopGuardTests(unittest.TestCase):

    def test_repeated_tool_call_is_blocked(self):
        client = LLMClient(api_key="test-key")
        calls = []

        def fake_request(payload, api_url=None, api_key=None):
            tool_messages = [
                item
                for item in payload.get("messages", [])
                if item.get("role") == "tool"
            ]
            if len(tool_messages) < 3:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "1",
                            "function": {
                                "name": "code_read",
                                "arguments": '{"path": "a.py"}',
                            },
                        }
                    ],
                }
            return {"content": "готово"}

        client._request = fake_request

        def execute(name, arguments):
            calls.append((name, arguments))
            return "same result"

        answer = client.ask_with_tools(
            prompt="x",
            system="",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "code_read",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            tool_executor=execute,
            max_iterations=6,
        )

        self.assertEqual(answer, "готово")
        self.assertEqual(len(calls), 2)

    def test_auto_verify_runs_before_final_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            state = CodeAgentState(path=Path(folder) / "state.json")
            state.begin_task("fix", folder)
            state.set_plan(["edit"])
            state.changed_files = [str(Path(folder) / "a.py")]
            state.verified = False
            client = LLMClient(api_key="test-key")
            calls = []

            def fake_request(payload, api_url=None, api_key=None):
                return {"content": "готово"}

            client._request = fake_request

            def execute(name, arguments):
                calls.append(name)
                state.verified = True
                return "OK"

            answer = client.ask_with_tools(
                prompt="x",
                system="",
                tools=[],
                tool_executor=execute,
                max_iterations=3,
                code_state=state,
            )

            self.assertEqual(answer, "готово")
            self.assertIn("code_verify", calls)


class CodeSafetyTests(unittest.TestCase):

    def test_telegram_token_is_redacted(self):
        token = "123456789:" + "B" * 35
        text = redact_secrets(f"token={token}")
        self.assertNotIn(token, text)
        self.assertIn("***", text)

    def test_autopilot_skips_confirmation_for_code_tools(self):
        safety = SafetyManager({"safety": {"autonomy": "balanced"}})
        safety.set_autopilot(True)
        spec = ToolSpec(
            name="code_edit",
            description="edit",
            parameters={"type": "object", "properties": {}},
            handler=lambda: None,
            category="code",
            danger="confirm",
        )
        with patch.object(safety, "confirm", return_value=False) as confirm:
            self.assertTrue(safety.before_tool(spec, {}))
            confirm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
