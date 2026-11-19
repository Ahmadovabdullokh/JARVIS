"""Единая точка с путями проекта.

Раньше BASE_DIR пересчитывался почти в каждом модуле. Теперь все
компоненты берут пути отсюда, чтобы не расходиться при упаковке.
"""

import sys
from pathlib import Path


def _app_base():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _app_base()
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
APP_DIR = RESOURCE_DIR / "app"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"
EXAMPLE_CONFIG_FILE = RESOURCE_DIR / "config" / "config.example.json"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"


def resource_path(*parts):
    return RESOURCE_DIR.joinpath(*parts)


def ensure_runtime_dirs():
    """Создаёт каталоги, без которых приложение не сможет писать данные."""

    for path in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
