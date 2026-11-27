"""Плагинная подсистема JARVIS.

Плагин — это модуль Python в каталоге ``plugins/`` (файл ``name.py`` или
пакет ``name/plugin.py``). Модуль должен предоставить один из вариантов:

* атрибут ``PLUGIN`` — экземпляр/класс ``JarvisPlugin``;
* функцию ``create_plugin()`` — возвращает плагин;
* функцию ``register(registry)`` (модульный стиль) и, опционально,
  ``MANIFEST`` / ``on_start`` / ``on_stop``.

Плагин объявляет манифест::

    {
        "name": "weather",
        "version": "1.0.0",
        "author": "you",
        "description": "...",
        "permissions": ["network"],
        "api": 1,
    }

Права носят декларативный характер и проверяются менеджером: если в
конфиге задан ``plugins.allowed_permissions``, плагин, запросивший
право вне списка, не загружается. Загрузка изолирована: сбой одного
плагина не роняет приложение, а частично зарегистрированные
инструменты откатываются.
"""

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logging import get_logger
from app.paths import BASE_DIR, RESOURCE_DIR

log = get_logger(__name__)

PLUGIN_API_VERSION = 1


def _default_plugins_dir() -> Path:
    for base in (BASE_DIR, RESOURCE_DIR):
        candidate = Path(base) / "plugins"
        if candidate.is_dir():
            return candidate
    return Path(BASE_DIR) / "plugins"


class JarvisPlugin:
    """Базовый класс плагина. Наследники переопределяют нужные хуки."""

    manifest_data: Dict[str, Any] = {}

    def manifest(self) -> Dict[str, Any]:
        return dict(self.manifest_data)

    def register(self, registry) -> None:
        """Регистрирует инструменты через registry.register()/registry.tool()."""

    def on_start(self, context) -> None:
        """Вызывается после успешной регистрации (контекст ToolContext)."""

    def on_stop(self) -> None:
        """Вызывается при выгрузке/перезагрузке плагина."""

    def on_message(self, text: str):
        """Возвращает строку-ответ или None."""

    def on_tool_call(self, name, arguments, result) -> None:
        """Наблюдатель за вызовами инструментов."""


class _ModulePlugin(JarvisPlugin):
    """Адаптер для модульного стиля (register/MANIFEST в модуле)."""

    def __init__(self, module):
        self._module = module
        self.manifest_data = getattr(module, "MANIFEST", {}) or {}

    def register(self, registry) -> None:
        self._module.register(registry)

    def on_start(self, context) -> None:
        handler = getattr(self._module, "on_start", None)
        if callable(handler):
            handler(context)

    def on_stop(self) -> None:
        handler = getattr(self._module, "on_stop", None)
        if callable(handler):
            handler()

    def on_message(self, text: str):
        handler = getattr(self._module, "on_message", None)
        if callable(handler):
            return handler(text)
        return None

    def on_tool_call(self, name, arguments, result) -> None:
        handler = getattr(self._module, "on_tool_call", None)
        if callable(handler):
            handler(name, arguments, result)


@dataclass
class LoadedPlugin:
    name: str
    version: str
    path: str
    instance: Any
    tool_names: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    description: str = ""

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "tools": list(self.tool_names),
            "permissions": list(self.permissions),
            "description": self.description,
        }


class PluginManager:
    """Обнаружение, загрузка, изоляция и перезагрузка плагинов."""

    def __init__(self, registry, plugins_dir=None, config=None):
        self.registry = registry
        config = config if isinstance(config, dict) else {}
        plugins_cfg = config.get("plugins", {})
        if not isinstance(plugins_cfg, dict):
            plugins_cfg = {}

        self.enabled = bool(plugins_cfg.get("enabled", True))
        disabled = plugins_cfg.get("disabled", [])
        self.disabled = {
            str(item).strip()
            for item in (disabled if isinstance(disabled, list) else [])
            if str(item).strip()
        }
        allowed = plugins_cfg.get("allowed_permissions", [])
        self.allowed_permissions = {
            str(item).strip()
            for item in (allowed if isinstance(allowed, list) else [])
            if str(item).strip()
        }
        configured_dir = plugins_cfg.get("dir")
        self.plugins_dir = Path(
            plugins_dir or configured_dir or _default_plugins_dir()
        )

        self._loaded: Dict[str, LoadedPlugin] = {}
        self.errors: List[tuple] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Обнаружение и загрузка
    # ------------------------------------------------------------------

    def _candidates(self):
        if not self.plugins_dir.is_dir():
            return []
        items = []
        for entry in sorted(self.plugins_dir.iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            if entry.is_file() and entry.suffix == ".py":
                items.append((entry.stem, entry))
            elif entry.is_dir():
                plugin_file = entry / "plugin.py"
                if plugin_file.is_file():
                    items.append((entry.name, plugin_file))
        return items

    def _import_module(self, name: str, path: Path):
        safe = "".join(ch if ch.isalnum() else "_" for ch in name)
        self._counter += 1
        module_name = f"jarvis_plugin_{safe}_{self._counter}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Не удалось создать spec для {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _adapt(module):
        plugin = getattr(module, "PLUGIN", None)
        if plugin is not None:
            if isinstance(plugin, type):
                plugin = plugin()
            return plugin
        factory = getattr(module, "create_plugin", None)
        if callable(factory):
            return factory()
        if callable(getattr(module, "register", None)):
            return _ModulePlugin(module)
        return None

    def _manifest(self, instance, fallback_name: str) -> Dict[str, Any]:
        try:
            manifest = instance.manifest()
        except Exception:
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        manifest = dict(manifest)
        manifest.setdefault("name", fallback_name)
        manifest.setdefault("version", "0.0.0")
        permissions = manifest.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []
        manifest["permissions"] = [
            str(item).strip() for item in permissions if str(item).strip()
        ]
        return manifest

    def _permitted(self, permissions: List[str]) -> Optional[str]:
        if not self.allowed_permissions:
            return None
        extra = sorted(set(permissions) - self.allowed_permissions)
        if extra:
            return (
                "запрошены неразрешённые права: " + ", ".join(extra)
            )
        return None

    def discover(self) -> List[str]:
        """Загружает все найденные плагины. Возвращает список имён."""

        self.errors = []
        if not self.enabled:
            return []
        loaded_names = []
        for name, path in self._candidates():
            if name in self.disabled:
                continue
            try:
                loaded = self._load_one(name, path)
            except Exception as error:
                self.errors.append(
                    (name, f"{type(error).__name__}: {error}")
                )
                log.warning("Плагин %s не загружен: %s", name, error)
                continue
            if loaded is not None:
                self._loaded[loaded.name] = loaded
                loaded_names.append(loaded.name)
        return loaded_names

    def _load_one(self, name: str, path: Path) -> Optional[LoadedPlugin]:
        module = self._import_module(name, path)
        instance = self._adapt(module)
        if instance is None:
            raise ValueError(
                "нет PLUGIN, create_plugin() или register()"
            )

        manifest = self._manifest(instance, name)
        plugin_name = str(manifest.get("name") or name).strip() or name
        version = str(manifest.get("version") or "0.0.0")

        api = manifest.get("api", PLUGIN_API_VERSION)
        try:
            api_version = int(api)
        except (TypeError, ValueError):
            api_version = PLUGIN_API_VERSION
        if api_version > PLUGIN_API_VERSION:
            raise ValueError(
                f"требует API {api_version}, поддерживается "
                f"{PLUGIN_API_VERSION}"
            )

        permissions = manifest.get("permissions", [])
        denied = self._permitted(permissions)
        if denied:
            raise PermissionError(denied)

        before = set(self.registry.names())
        try:
            instance.register(self.registry)
        except Exception:
            for tool_name in set(self.registry.names()) - before:
                self.registry.unregister(tool_name)
            raise
        added = sorted(set(self.registry.names()) - before)

        try:
            instance.on_start(self.registry.context)
        except Exception as error:
            log.warning(
                "Плагин %s: on_start упал: %s", plugin_name, error
            )

        return LoadedPlugin(
            name=plugin_name,
            version=version,
            path=str(path),
            instance=instance,
            tool_names=added,
            permissions=list(permissions),
            description=str(manifest.get("description") or ""),
        )

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    def _teardown(self, loaded: LoadedPlugin) -> None:
        try:
            loaded.instance.on_stop()
        except Exception as error:
            log.warning(
                "Плагин %s: on_stop упал: %s", loaded.name, error
            )
        for tool_name in loaded.tool_names:
            self.registry.unregister(tool_name)

    def reload(self) -> List[str]:
        for loaded in list(self._loaded.values()):
            self._teardown(loaded)
        self._loaded.clear()
        return self.discover()

    def stop_all(self) -> None:
        for loaded in list(self._loaded.values()):
            self._teardown(loaded)
        self._loaded.clear()

    def dispatch(self, event: str, *args, **kwargs) -> None:
        for loaded in list(self._loaded.values()):
            handler = getattr(loaded.instance, event, None)
            if not callable(handler):
                continue
            try:
                handler(*args, **kwargs)
            except Exception as error:
                log.warning(
                    "Плагин %s: %s упал: %s", loaded.name, event, error
                )

    def query(self, text: str):
        """Спрашивает плагины on_message; возвращает первый ответ."""
        for loaded in list(self._loaded.values()):
            handler = getattr(loaded.instance, "on_message", None)
            if not callable(handler):
                continue
            try:
                answer = handler(text)
            except Exception as error:
                log.warning(
                    "Плагин %s: on_message упал: %s", loaded.name, error
                )
                continue
            if answer:
                return str(answer)
        return None

    # ------------------------------------------------------------------
    # Отчёты
    # ------------------------------------------------------------------

    def loaded_plugins(self) -> List[Dict[str, Any]]:
        return [
            loaded.summary() for loaded in self._loaded.values()
        ]

    def report(self) -> str:
        if not self.enabled:
            return "Плагины отключены (plugins.enabled = false)."
        if not self._loaded and not self.errors:
            return "Плагины не найдены."
        lines = []
        for loaded in self._loaded.values():
            tools = ", ".join(loaded.tool_names) or "—"
            lines.append(
                f"{loaded.name} v{loaded.version}: {tools}"
            )
        for name, error in self.errors:
            lines.append(f"{name}: ОШИБКА — {error}")
        return "\n".join(lines)

    def _format_traceback(self) -> str:
        return traceback.format_exc()
