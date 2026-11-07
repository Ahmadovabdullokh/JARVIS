import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config as config_module
from app.paths import BASE_DIR


class PathsTests(unittest.TestCase):

    def test_base_dir_contains_app(self):
        self.assertTrue((BASE_DIR / "app" / "main.py").exists())


class ConfigValidationTests(unittest.TestCase):

    def test_defaults_and_wrong_types(self):
        warnings = config_module.validate_config(
            {
                "require_wake_word": "yes",
                "agent": {"autonomy": "unsafe", "max_iterations": "x"},
                "safety": {"confirm_destructive": "no"},
                "llm": {"provider": "unknown", "request_timeout": "slow"},
                "code": {"backend": "magic"},
                "tools": {"disabled_tools": "dev_hash"},
            }
        )
        text = " ".join(warnings)
        self.assertIn("require_wake_word", text)
        self.assertIn("agent.autonomy", text)
        self.assertIn("agent.max_iterations", text)
        self.assertIn("safety.confirm_destructive", text)
        self.assertIn("llm.provider", text)
        self.assertIn("llm.request_timeout", text)
        self.assertIn("code.backend", text)
        self.assertIn("tools.disabled_tools", text)

    def test_valid_config_has_no_warnings(self):
        self.assertEqual(
            config_module.validate_config(
                {
                    "require_wake_word": False,
                    "agent": {"autonomy": "balanced"},
                    "safety": {"autonomy": "balanced"},
                    "llm": {"provider": "deepseek"},
                    "code": {"backend": "deepseek"},
                    "tools": {"disabled_tools": []},
                }
            ),
            [],
        )

    def test_code_config_accepts_none(self):
        self.assertEqual(config_module.get_code_config(None), {})
        self.assertEqual(config_module.get_code_config({"code": []}), {})

    def test_code_backend_aliases(self):
        self.assertEqual(
            config_module.get_code_backend({"code": {"backend": "copilot"}}),
            "auto",
        )
        self.assertEqual(
            config_module.get_code_backend({"code": {"backend": "?"}}),
            "deepseek",
        )


class ConfigFileTests(unittest.TestCase):

    def test_load_config_uses_dotenv_override(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            sample = folder / "config.json"
            sample.write_text('{"chat_mode": "chat"}', encoding="utf-8")
            calls = []

            def loader(path, override=False):
                calls.append((path, override))

            with (
                patch.object(config_module, "CONFIG_FILE", sample),
                patch.object(config_module, "EXAMPLE_CONFIG_FILE", sample),
            ):
                config = config_module.load_config(dotenv_loader=loader)

            self.assertEqual(config["chat_mode"], "chat")
            self.assertTrue(calls)
            self.assertTrue(calls[0][1])

    def test_save_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            target = folder / "config.json"
            with (
                patch.object(config_module, "CONFIG_DIR", folder),
                patch.object(config_module, "CONFIG_FILE", target),
            ):
                config_module.save_config({"chat_mode": "code"})
                self.assertEqual(
                    config_module.read_config_file(),
                    {"chat_mode": "code"},
                )
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"chat_mode": "code"},
            )

    def test_read_invalid_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(config_module.read_config_file(broken), {})


if __name__ == "__main__":
    unittest.main()
