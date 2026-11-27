import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.pc_agent import PCAgent
from app.projects import (
    format_project_error,
    resolve_project_reference,
)


class ProjectResolverTests(unittest.TestCase):

    def test_natural_phrase_resolves_project(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            target = home / "PythonProject10"
            target.mkdir()
            result = resolve_project_reference(
                "проанализируй python project 10",
                projects_home=home,
            )
            self.assertEqual(result.status, "found")
            self.assertEqual(result.path, target.resolve())
            self.assertEqual(result.name, "PythonProject10")

    def test_exact_folder_name_resolves(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "PythonProject10").mkdir()
            result = resolve_project_reference(
                "глянь PythonProject10", projects_home=home
            )
            self.assertEqual(result.status, "found")
            self.assertEqual(result.name, "PythonProject10")

    def test_absolute_path_resolves(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "MyProject"
            target.mkdir()
            result = resolve_project_reference(
                f"проверь {target}",
                projects_home=Path(folder),
            )
            self.assertEqual(result.status, "found")
            self.assertEqual(result.path, target.resolve())

    def test_missing_project_reports_similar(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "PythonProject9").mkdir()
            result = resolve_project_reference(
                "python project 10", projects_home=home
            )
            self.assertEqual(result.status, "not_found")
            self.assertIn("PythonProject9", result.candidates)
            self.assertIn("PythonProject10", format_project_error(result))

    def test_no_reference_is_none(self):
        result = resolve_project_reference("привет, как дела?")
        self.assertEqual(result.status, "none")


class CodeProjectDefaultTests(unittest.TestCase):

    def test_current_project_used_without_argument(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            other = base / "PythonProject9"
            target = base / "PythonProject10"
            other.mkdir()
            target.mkdir()
            (target / "main.py").write_text("x = 1\n", encoding="utf-8")
            agent = PCAgent(
                config={"code": {"project": str(other)}}
            )
            agent.current_project = str(target)
            tree = agent.execute_tool("code_tree", {})
            self.assertIn("main.py", tree)

    def test_active_code_state_project_wins(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            other = base / "PythonProject9"
            target = base / "PythonProject10"
            other.mkdir()
            target.mkdir()
            (target / "main.py").write_text("x = 1\n", encoding="utf-8")
            agent = PCAgent(
                config={"code": {"project": str(other)}}
            )
            agent.code_state.begin_task("analyse", str(target))
            try:
                tree = agent.execute_tool("code_tree", {})
                self.assertIn("main.py", tree)
            finally:
                agent.code_state.finish()
