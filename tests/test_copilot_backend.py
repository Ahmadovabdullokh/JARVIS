import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.main import (
    copilot_backend_available,
    get_code_config,
    run_copilot_backend,
)


class FakeRegistry:

    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, tool, arguments):
        self.calls.append((tool, arguments))
        return self.result


def _agent(code_config, result):
    return SimpleNamespace(
        config={"code": code_config},
        registry=FakeRegistry(result),
    )


class GetCodeConfigTests(unittest.TestCase):

    def test_missing_config_is_empty_dict(self):
        self.assertEqual(get_code_config({}), {})
        self.assertEqual(get_code_config(None), {})
        self.assertEqual(get_code_config({"code": "мусор"}), {})


class BackendAvailableTests(unittest.TestCase):

    def test_vscode_always_available(self):
        self.assertTrue(copilot_backend_available("vscode"))

    def test_cli_checks_path(self):
        with patch.object(shutil, "which", return_value=None):
            self.assertFalse(copilot_backend_available("cli"))
            self.assertFalse(copilot_backend_available("auto"))
        with patch.object(shutil, "which", return_value="C:/copilot.cmd"):
            self.assertTrue(copilot_backend_available("cli"))
            self.assertTrue(copilot_backend_available("auto"))


class RunCopilotBackendTests(unittest.TestCase):

    def test_disabled_returns_none(self):
        agent = _agent({"enabled": False}, "результат")
        self.assertIsNone(run_copilot_backend(agent, "задача"))

    def test_auto_cli_missing_falls_back(self):
        agent = _agent({"project": ""}, "результат")
        with patch.object(shutil, "which", return_value=None):
            self.assertIsNone(run_copilot_backend(agent, "задача"))
        self.assertFalse(agent.registry.calls)

    def test_cli_missing_explicit_reports(self):
        agent = _agent({"backend": "cli", "project": ""}, "результат")
        with patch.object(shutil, "which", return_value=None):
            message = run_copilot_backend(agent, "задача")
        self.assertIsNotNone(message)
        self.assertIn("npm install -g @github/copilot", message)

    def test_cli_dispatch(self):
        agent = _agent(
            {
                "backend": "auto",
                "project": "C:/proj",
                "cli_args": ["--allow-all-tools"],
                "timeout": 60,
            },
            "Copilot: готово",
        )
        with patch.object(shutil, "which", return_value="copilot.cmd"):
            result = run_copilot_backend(agent, "исправь ошибку")
        self.assertEqual(result, "Copilot: готово")
        tool, arguments = agent.registry.calls[0]
        self.assertEqual(tool, "copilot_cli_task")
        self.assertEqual(arguments["task"], "исправь ошибку")
        self.assertEqual(arguments["project"], "C:/proj")
        self.assertEqual(arguments["cli_args"], ["--allow-all-tools"])
        self.assertEqual(arguments["timeout"], 60)

    def test_vscode_dispatch(self):
        agent = _agent(
            {"backend": "vscode", "project": "C:/proj"},
            "передано в чат",
        )
        result = run_copilot_backend(agent, "исправь ошибку")
        self.assertEqual(result, "передано в чат")
        tool, arguments = agent.registry.calls[0]
        self.assertEqual(tool, "copilot_vscode_task")
        self.assertEqual(arguments["project"], "C:/proj")

    def test_auto_failure_falls_back(self):
        agent = _agent(
            {"backend": "auto", "project": ""},
            "Ошибка: Copilot не завершил задание.",
        )
        with patch.object(shutil, "which", return_value="copilot.cmd"):
            self.assertIsNone(run_copilot_backend(agent, "задача"))

    def test_explicit_failure_is_reported(self):
        agent = _agent(
            {"backend": "cli", "project": ""},
            "Ошибка: папка проекта не найдена.",
        )
        with patch.object(shutil, "which", return_value="copilot.cmd"):
            message = run_copilot_backend(agent, "задача")
        self.assertIn("Ошибка", message)


if __name__ == "__main__":
    unittest.main()