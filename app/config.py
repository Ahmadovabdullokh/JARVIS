"""Загрузка, нормализация и сохранение конфигурации.

Раньше разбор config.json был размазан между app/main.py и launcher.py.
Теперь это единственный источник правды: загрузка с fallback на
config.example.json, мягкая валидация, атомарная запись и типизированные
секции для остальных модулей.
"""

import json
import os
from pathlib import Path

from app import persona
from app.paths import (
    BASE_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    EXAMPLE_CONFIG_FILE,
)

CHAT_MODES = ("chat", "tasks", "code")
AUTONOMY_LEVELS = ("safe", "balanced", "full")
CODE_BACKENDS = ("auto", "cli", "vscode", "deepseek")
PROVIDERS = ("deepseek", "groq", "ollama")

DEFAULT_CONFIG = {
    "require_wake_word": False,
    "transcript_preview": False,
    "chat_mode": "tasks",
    "memory_size": 50,
    "tts_offline_fallback": False,
    "agent": {
        "autonomy": "balanced",
        "max_iterations": 12,
        "max_tokens": 3000,
        "tool_result_limit": 16000,
        "tool_timeout_seconds": 120,
        "max_tools_per_request": 100,
        "code_tools_per_request": 28,
        "category_planning": True,
    },
    "safety": {
        "autonomy": "balanced",
        "confirm_destructive": True,
        "dry_run": False,
        "taint_tracking": True,
    },
    "code": {
        "enabled": True,
        "backend": "deepseek",
        "project": "",
        "max_iterations": 60,
        "timeout": 900,
        "fallback": True,
    },
    "llm": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "max_retries": 2,
        "retry_backoff": 0.8,
        "parallel_tool_calls": False,
        "request_timeout": 180,
        "session_history": 20,
    },
}


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def load_config(dotenv_loader=None, validate=True):
    """Читает config.json, при отсутствии — config.example.json.

    dotenv_loader передаётся явно, чтобы тесты могли подменять
    app.main.load_dotenv и проверять override.
    """

    loader = dotenv_loader
    if loader is None:
        try:
            from dotenv import load_dotenv as loader
        except ImportError:
            loader = None

    if loader is not None:
        loader(BASE_DIR / ".env", override=True)

    config_path = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_CONFIG_FILE
    if not config_path.exists():
        raise FileNotFoundError(
            "Не найден файл конфигурации.\n"
            f"Проверь наличие:\n{CONFIG_FILE}\nили\n{EXAMPLE_CONFIG_FILE}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна содержать JSON-объект.")

    if validate:
        warnings = validate_config(config)
        if warnings:
            from app.logging import get_logger

            logger = get_logger(__name__)
            for warning in warnings:
                logger.warning("config: %s", warning)

    return config


def read_config_file(path=None):
    """Читает конфиг без выброса исключений (для UI и диагностики)."""

    target = Path(path) if path else (
        CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_CONFIG_FILE
    )
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config):
    """Атомарно пишет config.json, не оставляя полузаписанных файлов."""

    if not isinstance(config, dict):
        raise ValueError("Конфигурация должна быть JSON-объектом.")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(
        json.dumps(config, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    temp.replace(CONFIG_FILE)
    return CONFIG_FILE


def validate_config(config):
    """Мягкая проверка типов и диапазонов. Возвращает список замечаний."""

    warnings = []
    if not isinstance(config, dict):
        return ["Конфигурация должна быть JSON-объектом."]

    def check_type(section, key, expected, label=None):
        container = _as_dict(config.get(section)) if section else config
        if key not in container:
            return
        value = container.get(key)
        if expected is float and isinstance(value, int) and not isinstance(
            value, bool
        ):
            return
        if not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            name = label or (f"{section}.{key}" if section else key)
            warnings.append(
                f"{name}: ожидался {expected.__name__}, "
                f"получено {type(value).__name__}."
            )

    check_type(None, "require_wake_word", bool)
    check_type(None, "transcript_preview", bool)
    check_type(None, "memory_size", int)
    check_type(None, "max_speech_seconds", float)
    check_type(None, "silence_duration", float)

    agent = _as_dict(config.get("agent"))
    if agent.get("autonomy") not in (None, *AUTONOMY_LEVELS):
        warnings.append(
            "agent.autonomy: допустимо safe, balanced или full."
        )
    for key in ("max_iterations", "max_tokens", "tool_timeout_seconds"):
        check_type("agent", key, int)

    safety = _as_dict(config.get("safety"))
    if safety.get("autonomy") not in (None, *AUTONOMY_LEVELS):
        warnings.append(
            "safety.autonomy: допустимо safe, balanced или full."
        )
    for key in ("confirm_destructive", "dry_run", "taint_tracking"):
        check_type("safety", key, bool)

    llm = _as_dict(config.get("llm"))
    provider = str(llm.get("provider") or "deepseek").lower()
    if provider not in PROVIDERS:
        warnings.append(
            f"llm.provider: неизвестный провайдер {provider!r}; "
            "будет использован deepseek."
        )
    check_type("llm", "request_timeout", int)
    check_type("llm", "max_retries", int)

    code = _as_dict(config.get("code"))
    backend = str(code.get("backend") or "deepseek").lower()
    if backend not in CODE_BACKENDS:
        warnings.append(
            f"code.backend: неизвестный backend {backend!r}; "
            "будет использован deepseek."
        )

    tools = _as_dict(config.get("tools"))
    for key in ("enabled_categories", "disabled_tools"):
        if key in tools and not isinstance(tools.get(key), list):
            warnings.append(f"tools.{key}: ожидался список.")

    return warnings


def get_groq_config(config: dict) -> dict:
    """Настройки Groq: ключ, STT, VAD и vision-модель."""

    config = _as_dict(config)
    groq = _as_dict(config.get("groq"))

    api_key = (
        groq.get("api_key")
        or config.get("groq_api_key")
        or os.getenv("GROQ_API_KEY")
        or ""
    )

    model = (
        groq.get("model")
        or config.get("llm_model")
        or "openai/gpt-oss-120b"
    )

    vision_model = (
        groq.get("vision_model")
        or config.get("vision_model")
        or "qwen/qwen3.8-27b"
    )

    stt_model = (
        groq.get("stt_model")
        or config.get("stt_model")
        or config.get("groq_model")
        or "whisper-large-v3-turbo"
    )

    stt_prompt = (
        groq.get("stt_prompt")
        or config.get("stt_prompt")
        or "Джарвис, открой браузер. Джарвис, статус систем."
    )

    enabled = groq.get("enabled", config.get("llm_enabled", True))

    return {
        "api_key": api_key,
        "model": model,
        "vision_model": vision_model,
        "stt_model": stt_model,
        "stt_prompt": stt_prompt,
        "enabled": bool(enabled),
        "sample_rate": int(
            groq.get("sample_rate", config.get("audio_sample_rate", 16000))
        ),
        "silence_threshold": float(
            groq.get(
                "silence_threshold",
                config.get("silence_threshold", 0.005),
            )
        ),
        "min_speech_seconds": float(
            groq.get(
                "min_speech_seconds",
                config.get("min_speech_seconds", 0.25),
            )
        ),
        "max_speech_seconds": float(
            groq.get(
                "max_speech_seconds",
                config.get("max_speech_seconds", 12.0),
            )
        ),
        "silence_duration": float(
            groq.get(
                "silence_duration",
                config.get("silence_duration", 0.7),
            )
        ),
        "initial_silence_seconds": float(
            groq.get(
                "initial_silence_seconds",
                config.get("initial_silence_seconds", 1.2),
            )
        ),
        "noise_adapt_k": float(
            groq.get(
                "noise_adapt_k",
                config.get("stt_noise_adapt_k", 3.0),
            )
        ),
        "noise_max_ratio": float(
            groq.get(
                "noise_max_ratio",
                config.get("stt_noise_max_ratio", 8.0),
            )
        ),
        "language": str(
            groq.get("language", config.get("stt_language", "ru"))
        ),
    }


def get_llm_config(config: dict) -> dict:
    """Настройки языковой модели (по умолчанию DeepSeek)."""

    config = _as_dict(config)
    llm = _as_dict(config.get("llm"))
    deepseek = _as_dict(config.get("deepseek"))

    provider = str(
        llm.get("provider") or config.get("llm_provider") or "deepseek"
    ).strip().lower()
    provider = {
        "deep-seek": "deepseek",
        "deepseek-ai": "deepseek",
    }.get(provider, provider)

    if provider == "deepseek":
        api_key = (
            llm.get("api_key")
            or deepseek.get("api_key")
            or config.get("deepseek_api_key")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("LLM_API_KEY")
            or ""
        )
        model = (
            llm.get("model")
            or deepseek.get("model")
            or config.get("deepseek_model")
            or "deepseek-chat"
        )
        base_url = llm.get("base_url") or deepseek.get("base_url") or ""
    elif provider == "groq":
        api_key = (
            llm.get("api_key")
            or config.get("groq_api_key")
            or os.getenv("GROQ_API_KEY")
            or ""
        )
        model = (
            llm.get("model")
            or config.get("llm_model")
            or "openai/gpt-oss-120b"
        )
        base_url = str(llm.get("base_url") or "")
    elif provider == "ollama":
        api_key = str(llm.get("api_key") or "")
        model = llm.get("model") or config.get("llm_model") or "qwen2.5:7b"
        base_url = (
            llm.get("base_url")
            or "http://localhost:11434/v1/chat/completions"
        )
    else:
        api_key = llm.get("api_key") or os.getenv("LLM_API_KEY") or ""
        model = llm.get("model") or config.get("llm_model") or ""
        base_url = str(llm.get("base_url") or "")

    fallback_base_url = str(llm.get("fallback_base_url") or "").strip()
    fallback_model = str(llm.get("fallback_model") or "").strip()
    fallback_api_key = str(llm.get("fallback_api_key") or "").strip()

    if (
        provider == "deepseek"
        and not fallback_base_url
        and llm.get("auto_fallback", True)
    ):
        groq_key = config.get("groq_api_key") or os.getenv("GROQ_API_KEY") or ""
        if groq_key:
            fallback_base_url = (
                "https://api.groq.com/openai/v1/chat/completions"
            )
            fallback_model = (
                llm.get("auto_fallback_model") or "openai/gpt-oss-120b"
            )
            fallback_api_key = str(groq_key)

    return {
        "provider": provider,
        "api_key": str(api_key or "").strip(),
        "model": str(model or "").strip(),
        "base_url": str(base_url or "").strip(),
        "fallback_base_url": fallback_base_url,
        "fallback_model": fallback_model,
        "fallback_api_key": fallback_api_key,
        "enabled": bool(llm.get("enabled", config.get("use_llm", True))),
        "max_retries": int(llm.get("max_retries", 2)),
        "retry_backoff": float(llm.get("retry_backoff", 0.8)),
        "parallel_tool_calls": bool(llm.get("parallel_tool_calls", False)),
        "session_history": int(
            llm.get("session_history", config.get("llm_history_size", 20))
        ),
        "request_timeout": int(llm.get("request_timeout", 180)),
    }


def get_tts_config(config: dict) -> dict:
    """Настройки синтеза речи, совместимые с конструктором TTS."""

    config = _as_dict(config)
    tts = _as_dict(config.get("tts"))

    voice = str(
        tts.get(
            "voice",
            config.get("tts_voice", "en-US-AndrewMultilingualNeural"),
        )
    )

    voices = tts.get("voices") or config.get("tts_voices") or []
    if not isinstance(voices, list):
        voices = []

    return {
        "rate": int(tts.get("rate", config.get("tts_rate", 175))),
        "voice": voice,
        "pitch": str(tts.get("pitch", config.get("tts_pitch", "-8Hz"))),
        "voices": [str(item) for item in voices],
    }


def get_persona_config(config: dict) -> dict:
    return persona.normalize_config(config)


def get_wake_config(config: dict) -> dict:
    config = _as_dict(config)
    wake_words = config.get("wake_words") or [
        "джарвис",
        "jarvis",
        "джарвиз",
        "дарвис",
    ]

    if not isinstance(wake_words, list):
        wake_words = ["джарвис"]

    return {
        "enabled": bool(
            config.get(
                "require_wake_word",
                config.get("hot_phrase_enabled", False),
            )
        ),
        "wake_words": [
            str(word).strip() for word in wake_words if str(word).strip()
        ],
        "cooldown": float(config.get("wake_word_cooldown", 1.5)),
        "ack": str(config.get("wake_ack", "")).strip(),
        "follow_up_seconds": float(config.get("follow_up_seconds", 8.0)),
    }


def get_code_config(config: dict) -> dict:
    config = _as_dict(config)
    return _as_dict(config.get("code"))


def get_code_backend(config: dict) -> str:
    backend = str(
        get_code_config(config).get("backend", "deepseek")
    ).strip().lower()
    aliases = {
        "deep-seek": "deepseek",
        "agent": "deepseek",
        "llm": "deepseek",
        "copilot": "auto",
    }
    backend = aliases.get(backend, backend)
    return backend if backend in CODE_BACKENDS else "deepseek"


def code_backend_uses_copilot(config: dict) -> bool:
    return get_code_backend(config) in {"auto", "cli", "vscode"}
