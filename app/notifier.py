"""Push-уведомления JARVIS в Telegram.

Отправляет сообщения через бота (те же JARVIS_TELEGRAM_BOT_TOKEN /
JARVIS_TELEGRAM_CHAT_ID, что и инструмент telegram_send), чтобы
удалённый пользователь узнавал о завершении задач и ошибках,
даже когда приложение свёрнуто.

Включается в config.json:

    "notifications": {
        "telegram": true,
        "tasks": true,
        "errors": true
    }

По умолчанию всё выключено.
"""

import json
import os
import threading
import time

import requests

from app.logging import get_logger
from app.paths import CONFIG_FILE

log = get_logger(__name__)

_config_cache = {"mtime": 0.0, "data": {}}


def _notifications_config():
    """Читает секцию notifications из config.json (кэш ~30 c)."""

    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    now = time.monotonic()
    if (
        _config_cache["data"]
        and now - _config_cache["mtime"] < 30.0
        and mtime == _config_cache.get("file_mtime", -1.0)
    ):
        return _config_cache["data"]

    data = {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        section = raw.get("notifications")
        if isinstance(section, dict):
            data = section
    except (OSError, ValueError):
        pass

    _config_cache["data"] = data
    _config_cache["mtime"] = now
    _config_cache["file_mtime"] = mtime
    return data


def _credentials():
    token = (
        os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat = (
        os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "").strip()
    )
    if not token or not chat:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            integrations = raw.get("integrations") or {}
            token = token or str(
                integrations.get("telegram_bot_token") or ""
            ).strip()
            chat = chat or str(
                integrations.get("telegram_chat_id") or ""
            ).strip()
        except (OSError, ValueError):
            pass
    return token, chat


def _send(token, chat, text):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000]},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except Exception as error:
        log.info(f"[NOTIFY] Telegram: {type(error).__name__}: {error}")
        return False


def notify(text, kind="info"):
    """Отправляет уведомление в Telegram, если оно включено.

    kind: "tasks" | "errors" | "system" — фильтруется конфигом.
    Никогда не бросает исключений и не блокирует вызывающий поток.
    """

    text = str(text or "").strip()
    if not text:
        return

    config = _notifications_config()
    if not config.get("telegram"):
        return
    flag = {
        "tasks": "tasks",
        "errors": "errors",
        "system": "system",
    }.get(kind, "system")
    if not config.get(flag, flag == "system"):
        return

    token, chat = _credentials()
    if not token or not chat:
        return

    threading.Thread(
        target=_send,
        args=(token, chat, text),
        name="JARVIS-Notify",
        daemon=True,
    ).start()


def notify_task(title, status, detail=""):
    icon = {"done": "✅", "failed": "❌", "cancelled": "⏹"}.get(
        status, "ℹ️"
    )
    text = f"{icon} JARVIS: {title}\nСтатус: {status}"
    if detail:
        text += f"\n{str(detail)[:500]}"
    notify(text, kind="tasks" if status == "done" else "errors")
