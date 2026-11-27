import tempfile
import unittest
from pathlib import Path

from app.plugins import PluginManager
from app.tools.base import ToolRegistry

GOOD_PLUGIN = """
from app.plugins import JarvisPlugin

MANIFEST = {
    "name": "good",
    "version": "1.2.3",
    "permissions": ["network"],
    "api": 1,
}


class GoodPlugin(JarvisPlugin):
    manifest_data = MANIFEST

    def register(self, registry):
        registry.tool(
            "good_hello",
            "Сказать привет из плагина.",
            {"type": "object", "properties": {}, "required": []},
            category="general",
        )(lambda: "hello from plugin")


PLUGIN = GoodPlugin()
"""

BROKEN_PLUGIN = """
raise RuntimeError("boom")
"""

NEEDS_PERMISSION_PLUGIN = """
from app.plugins import JarvisPlugin

MANIFEST = {
    "name": "needs_files",
    "version": "0.1.0",
    "permissions": ["files"],
    "api": 1,
}


class P(JarvisPlugin):
    manifest_data = MANIFEST

    def register(self, registry):
        registry.tool(
            "needs_files_tool",
            "x",
            {"type": "object", "properties": {}, "required": []},
            category="general",
        )(lambda: "x")


PLUGIN = P()
"""

MODULE_STYLE_PLUGIN = """
MANIFEST = {"name": "module_style", "version": "2.0.0", "api": 1}


def register(registry):
    registry.tool(
        "module_ping",
        "ping",
        {"type": "object", "properties": {}, "required": []},
        category="general",
    )(lambda: "pong")
"""


class PluginManagerTests(unittest.TestCase):

    def _dir(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, content in files.items():
            (root / name).write_text(content, encoding="utf-8")
        return root

    def test_loads_plugin_and_registers_tool(self):
        root = self._dir({"good.py": GOOD_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(registry, plugins_dir=root)
        loaded = manager.discover()
        self.assertEqual(loaded, ["good"])
        self.assertIsNotNone(registry.get("good_hello"))
        self.assertEqual(registry.execute("good_hello"), "hello from plugin")
        self.assertEqual(manager.errors, [])

    def test_module_style_plugin(self):
        root = self._dir({"mod.py": MODULE_STYLE_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(registry, plugins_dir=root)
        manager.discover()
        self.assertIsNotNone(registry.get("module_ping"))

    def test_broken_plugin_is_isolated(self):
        root = self._dir({
            "good.py": GOOD_PLUGIN,
            "broken.py": BROKEN_PLUGIN,
        })
        registry = ToolRegistry()
        manager = PluginManager(registry, plugins_dir=root)
        loaded = manager.discover()
        self.assertEqual(loaded, ["good"])
        self.assertIsNotNone(registry.get("good_hello"))
        self.assertEqual(len(manager.errors), 1)
        self.assertEqual(manager.errors[0][0], "broken")

    def test_permission_enforcement(self):
        root = self._dir({"needs.py": NEEDS_PERMISSION_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(
            registry,
            plugins_dir=root,
            config={"plugins": {"allowed_permissions": ["network"]}},
        )
        loaded = manager.discover()
        self.assertEqual(loaded, [])
        self.assertIsNone(registry.get("needs_files_tool"))
        self.assertEqual(len(manager.errors), 1)

    def test_disabled_plugin_skipped(self):
        root = self._dir({"good.py": GOOD_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(
            registry,
            plugins_dir=root,
            config={"plugins": {"disabled": ["good"]}},
        )
        loaded = manager.discover()
        self.assertEqual(loaded, [])
        self.assertIsNone(registry.get("good_hello"))

    def test_reload_keeps_tools(self):
        root = self._dir({"good.py": GOOD_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(registry, plugins_dir=root)
        manager.discover()
        loaded = manager.reload()
        self.assertEqual(loaded, ["good"])
        self.assertIsNotNone(registry.get("good_hello"))

    def test_stop_all_unregisters(self):
        root = self._dir({"good.py": GOOD_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(registry, plugins_dir=root)
        manager.discover()
        manager.stop_all()
        self.assertIsNone(registry.get("good_hello"))

    def test_plugins_can_be_disabled_globally(self):
        root = self._dir({"good.py": GOOD_PLUGIN})
        registry = ToolRegistry()
        manager = PluginManager(
            registry,
            plugins_dir=root,
            config={"plugins": {"enabled": False}},
        )
        self.assertEqual(manager.discover(), [])


if __name__ == "__main__":
    unittest.main()
