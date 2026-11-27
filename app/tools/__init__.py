import importlib

MODULES = [
    "generic",
    "capabilities",
    "files",
    "system",
    "processes",
    "windows",
    "apps",
    "input",
    "screen",
    "media",
    "network",
    "browser",
    "office",
    "communication",
    "dev",
    "coding",
    "security",
    "productivity",
    "knowledge",
    "hardware",
    "memory_tools",
    "automation",
    "ops",
]

LOAD_ERRORS = []

PLUGIN_MANAGER = None


def register_all_tools(
    registry,
    strict=False,
    plugins=None,
    config=None,
    plugins_dir=None,
):
    loaded = []
    errors = []
    for name in MODULES:
        try:
            module = importlib.import_module(f"app.tools.{name}")
            module.register(registry)
            loaded.append(name)
        except Exception as error:
            errors.append((name, f"{type(error).__name__}: {error}"))
            if strict:
                raise
    LOAD_ERRORS.clear()
    LOAD_ERRORS.extend(errors)

    global PLUGIN_MANAGER
    if plugins is None:
        plugins = True
    if plugins:
        try:
            from app.plugins import PluginManager

            manager = PluginManager(
                registry,
                plugins_dir=plugins_dir,
                config=config,
            )
            manager.discover()
            PLUGIN_MANAGER = manager
        except Exception as error:
            errors.append(
                ("plugins", f"{type(error).__name__}: {error}")
            )
            LOAD_ERRORS.append(
                ("plugins", f"{type(error).__name__}: {error}")
            )

    return loaded, errors


def get_plugin_manager():
    return PLUGIN_MANAGER


def load_report():
    lines = []
    if not LOAD_ERRORS:
        lines.append("Все модули инструментов загружены.")
    else:
        lines.extend(
            f"{name}: {error}" for name, error in LOAD_ERRORS
        )
    if PLUGIN_MANAGER is not None:
        lines.append("Плагины: " + PLUGIN_MANAGER.report())
    return "\n".join(lines)
