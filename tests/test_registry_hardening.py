import time
import unittest

from app.tools.base import (
    ToolRegistry,
    ToolSpec,
    validate_arguments,
)


class ArgumentValidationTests(unittest.TestCase):

    def test_additional_properties_are_rejected(self):
        parameters = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }
        self.assertIn(
            "Неизвестные аргументы",
            validate_arguments(parameters, {"path": "x", "extra": 1}),
        )
        self.assertIsNone(
            validate_arguments(parameters, {"path": "x"})
        )

    def test_numeric_bounds(self):
        parameters = {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                }
            },
        }
        self.assertIn(
            ">= 1",
            validate_arguments(parameters, {"count": 0}),
        )
        self.assertIn(
            "<= 5",
            validate_arguments(parameters, {"count": 6}),
        )
        self.assertIsNone(validate_arguments(parameters, {"count": 3}))

    def test_huge_string_is_rejected(self):
        parameters = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
        self.assertIn(
            "слишком длинный",
            validate_arguments(parameters, {"text": "x" * 1_000_001}),
        )


class RegistryLifecycleTests(unittest.TestCase):

    def test_close_is_idempotent(self):
        registry = ToolRegistry()
        registry.close()
        registry.close()

    def test_timeout_reports_background_work(self):
        registry = ToolRegistry(max_workers=1)
        registry.register(
            ToolSpec(
                name="slow",
                description="slow",
                parameters={"type": "object", "properties": {}},
                handler=lambda: time.sleep(0.3) or "ok",
                timeout=0.05,
            )
        )
        try:
            result = registry.execute_result("slow", {})
            self.assertEqual(result.status, "timeout")
            self.assertIn("фоне", result.text)
        finally:
            registry.close()

    def test_unknown_and_disabled_tools(self):
        registry = ToolRegistry()
        self.assertIn("Неизвестный", registry.execute("missing", {}))
        registry.register(
            ToolSpec(
                name="hidden",
                description="hidden",
                parameters={"type": "object", "properties": {}},
                handler=lambda: "ok",
                enabled=False,
            )
        )
        self.assertEqual(
            registry.execute_result("hidden", {}).status,
            "denied",
        )
        registry.close()


if __name__ == "__main__":
    unittest.main()
