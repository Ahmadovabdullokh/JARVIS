"""Единая точка с путями проекта.

Раньше BASE_DIR пересчитывался почти в каждом модуле. Теперь все
компоненты берут пути отсюда, чтобы не расходиться при упаковке.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"
EXAMPLE_CONFIG_FILE = CONFIG_DIR / "config.example.json"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"


def ensure_runtime_dirs():
    """Создаёт каталоги, без которых приложение не сможет писать данные."""

    for path in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
