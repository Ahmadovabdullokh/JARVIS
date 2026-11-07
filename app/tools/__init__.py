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


def register_all_tools(registry, strict=False):
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
    return loaded, errors


def load_report():
    if not LOAD_ERRORS:
        return "Все модули инструментов загружены."
    return "\n".join(
        f"{name}: {error}" for name, error in LOAD_ERRORS
    )
