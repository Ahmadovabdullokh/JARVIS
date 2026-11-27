"""Минимальная локализация интерфейсных строк (ru/en).

Строки лежат в ``app/locales/<lang>.json`` в виде плоских ключей
(``status.ready.label``). Перевод не найден — возвращается исходный ключ
или заданный default, поэтому отсутствие строки ничего не ломает.

Полное покрытие всех экранов — постепенная задача; модуль даёт механизм,
переключатель языка и общий словарь без внешних зависимостей.
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict

from app.paths import BASE_DIR, RESOURCE_DIR

SUPPORTED_LANGUAGES = ("ru", "en")
DEFAULT_LANGUAGE = "ru"

_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, str]] = {}
_CURRENT = os.environ.get("JARVIS_LANG", DEFAULT_LANGUAGE)


def _locales_dir() -> Path:
    for base in (RESOURCE_DIR, BASE_DIR):
        candidate = Path(base) / "app" / "locales"
        if candidate.is_dir():
            return candidate
    return Path(BASE_DIR) / "app" / "locales"


def _normalize(language) -> str:
    code = str(language or "").strip().lower()
    if code.startswith("en"):
        return "en"
    if code.startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


def available_languages():
    directory = _locales_dir()
    if not directory.is_dir():
        return list(SUPPORTED_LANGUAGES)
    found = [
        path.stem
        for path in directory.glob("*.json")
        if path.stem in SUPPORTED_LANGUAGES
    ]
    return found or list(SUPPORTED_LANGUAGES)


def _load(language) -> Dict[str, str]:
    code = _normalize(language)
    with _LOCK:
        if code in _CACHE:
            return _CACHE[code]
        data: Dict[str, str] = {}
        path = _locales_dir() / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        _CACHE[code] = {
            str(key): str(value) for key, value in data.items()
        }
        return _CACHE[code]


def set_language(language) -> str:
    global _CURRENT
    code = _normalize(language)
    with _LOCK:
        _CURRENT = code
    return code


def get_language() -> str:
    return _CURRENT


def translate(key, default=None, **fmt) -> str:
    code = _CURRENT
    value = _load(code).get(str(key))
    if value is None and code != DEFAULT_LANGUAGE:
        value = _load(DEFAULT_LANGUAGE).get(str(key))
    if value is None:
        value = default if default is not None else str(key)
    if fmt:
        try:
            value = value.format(**fmt)
        except (KeyError, IndexError, ValueError):
            pass
    return value


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


t = translate
