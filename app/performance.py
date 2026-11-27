"""Профиль производительности по железу.

На слабом ноутбуке (2 физических ядра, 8 ГБ RAM) тяжёлые настройки
камеры, жестов и агента съедают заметную долю CPU. Профиль ничего не
перезаписывает в config.json: значения применяются как ограничения
при чтении, поэтому выключение профиля возвращает исходные настройки.

Ручной выбор: ``performance.tier`` в config.json или переменная
окружения ``JARVIS_TIER=low|standard|high``. ``performance.auto:
false`` отключает автопрофиль (tier = standard).
"""

import os
import threading
import time

try:
    import psutil
except Exception:  # pragma: no cover - psutil в requirements
    psutil = None

from app import config as config_module

TIERS = ("low", "standard", "high")
CACHE_TTL = 60.0

_LOW_CAMERA_LIMITS = (
    ("stream_fps", 12.0, float),
    ("analyze_fps", 8.0, float),
    ("jpeg_quality", 78, int),
    ("sharpness", 0.25, float),
    ("max_clients", 2, int),
)

_LOCK = threading.Lock()
_CACHE = {"tier": None, "at": 0.0, "hardware": None}


def _config():
    try:
        return config_module.read_config_file() or {}
    except Exception:
        return {}


def _section(config, name):
    value = config.get(name)
    return value if isinstance(value, dict) else {}


def reset_cache():
    """Сбрасывает кэш определения (тесты, смена настроек)."""

    with _LOCK:
        _CACHE.update({"tier": None, "at": 0.0, "hardware": None})


def read_hardware():
    """Возвращает физические ядра, потоки и объём RAM в ГБ."""

    if psutil is None:
        return {"cores": 0, "threads": 0, "ram_gb": 0.0}
    try:
        logical = int(psutil.cpu_count(logical=True) or 0)
        physical = int(psutil.cpu_count(logical=False) or 0)
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return {"cores": 0, "threads": 0, "ram_gb": 0.0}
    return {
        "cores": physical or logical,
        "threads": logical,
        "ram_gb": round(ram_gb, 1),
    }


def detect_tier(force=False, hardware=None):
    """Определяет tier: low / standard / high."""

    env = os.environ.get("JARVIS_TIER", "").strip().lower()
    if env in TIERS:
        return env

    now = time.monotonic()
    with _LOCK:
        cached = _CACHE["tier"]
        if not force and cached and now - _CACHE["at"] < CACHE_TTL:
            return cached

    perf = _section(_config(), "performance")
    manual = str(perf.get("tier") or "auto").strip().lower()
    if manual in TIERS:
        return manual
    if perf.get("auto", True) is False:
        return "standard"

    info = hardware or read_hardware()
    cores = int(info.get("cores") or 0)
    ram_gb = float(info.get("ram_gb") or 0.0)
    if (cores and cores <= 2) or (ram_gb and ram_gb <= 8.5):
        tier = "low"
    elif cores >= 8 and ram_gb >= 16:
        tier = "high"
    else:
        tier = "standard"

    with _LOCK:
        _CACHE.update({"tier": tier, "at": now, "hardware": info})
    return tier


def is_low():
    return detect_tier() == "low"


def profile():
    """Снимок профиля для логов и UI."""

    tier = detect_tier()
    with _LOCK:
        info = dict(_CACHE["hardware"] or {})
    if not info:
        info = read_hardware()
    return {
        "tier": tier,
        "low": tier == "low",
        "cores": info.get("cores", 0),
        "threads": info.get("threads", 0),
        "ram_gb": info.get("ram_gb", 0.0),
    }


def clamp_camera(settings):
    """Ограничивает настройки камеры на low-профиле (in place)."""

    if detect_tier() != "low":
        return settings
    for key, maximum, cast in _LOW_CAMERA_LIMITS:
        if key not in settings:
            continue
        try:
            settings[key] = cast(min(float(settings[key]), float(maximum)))
        except (TypeError, ValueError):
            continue
    return settings


def clamp_gestures(settings):
    """Ограничивает настройки жестов на low-профиле (in place)."""

    if detect_tier() != "low":
        return settings
    try:
        settings["num_hands"] = min(int(settings.get("num_hands") or 1), 1)
    except (TypeError, ValueError):
        settings["num_hands"] = 1
    return settings


def tool_workers(default=8):
    return 3 if is_low() else default


def task_workers(default=4):
    return 2 if is_low() else default


def parallel_workers(default=4):
    return 2 if is_low() else default


def tool_budget(default=100):
    return 40 if is_low() else default


def clamp_tool_limit(limit):
    """Урезает число схем инструментов в одном запросе к LLM."""

    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = tool_budget()
    if is_low():
        return max(20, min(value, 40))
    return value


def category_planning_enabled():
    """На low-профиле лишний LLM-раунд планирования не окупается."""

    return not is_low()


def ui_lite_default():
    return is_low()


def mic_interval(default=0.3):
    return 0.5 if is_low() else default


def overlay_fps(default=12):
    """Частота перерисовки landmarks для MJPEG-превью."""

    return 6 if is_low() else default


def poll_interval_ms(default=150):
    return 250 if is_low() else default


def bootstrap_payload():
    info = profile()
    return {
        "tier": info["tier"],
        "ui_lite": ui_lite_default(),
        "poll_ms": poll_interval_ms(),
        "cores": info["cores"],
        "threads": info["threads"],
        "ram_gb": info["ram_gb"],
    }
