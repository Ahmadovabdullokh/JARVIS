"""Push-уведомления JARVIS в Telegram.

Отправляет сообщения через бота (те же JARVIS_TELEGRAM_BOT_TOKEN /
JARVIS_TELEGRAM_CHAT_ID, что и инструмент telegram_send), чтобы
удалённый пользователь узнавал о завершении задач и ошибках,
даже когда приложение свёрнуто.

Включается в config.json:

    "notifications": {
        "telegram": true,
        "tasks": true,
        "errors": true,
        "system": true
    }

Если chat_id ещё не известен, но бот уже получил сообщение от
пользователя, адрес определяется автоматически через getUpdates.
Быстрая проверка:

    python -m app.notifier --test
"""

import argparse
import json
import os
import threading
import time

import requests

from app import config as config_module
from app.logging import get_logger
from app.paths import CONFIG_FILE

log = get_logger(__name__)

_config_cache = {"mtime": 0.0, "data": {}}
_detect_lock = threading.Lock()
DEFAULT_SECTION = {
    "telegram": False,
    "tasks": True,
    "errors": True,
    "system": True,
}


def _raw_config():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_config(data):
    try:
        config_module.save_config(data)
        return True
    except Exception as error:
        log.info(f"[NOTIFY] Не удалось сохранить config: {error}")
        return False


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
    token = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "").strip()
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


def _detect_chat_id_unlocked(token):
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]'},
            timeout=15,
        )
        data = response.json()
    except Exception as error:
        log.info(
            f"[NOTIFY] getUpdates: {type(error).__name__}: {error}"
        )
        return ""

    if not data.get("ok"):
        log.info(
            "[NOTIFY] getUpdates отклонён: %s",
            data.get("description", "unknown"),
        )
        return ""

    chat_id = ""
    for update in reversed(data.get("result") or []):
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        value = chat.get("id")
        if value:
            chat_id = str(value)
            break

    if not chat_id:
        return ""

    raw = _raw_config()
    if raw:
        integrations = raw.setdefault("integrations", {})
        if not isinstance(integrations, dict):
            integrations = {}
            raw["integrations"] = integrations
        integrations["telegram_chat_id"] = chat_id
        _save_config(raw)
        log.info("[NOTIFY] chat_id Telegram определён и сохранён.")
    return chat_id


def detect_chat_id(token=""):
    """Ищет chat_id в последних сообщениях бота и сохраняет его."""

    token = token or _credentials()[0]
    if not token:
        return ""
    with _detect_lock:
        return _detect_chat_id_unlocked(token)


def enable(tasks=True, errors=True, system=True):
    """Включает Telegram-уведомления в config.json."""

    raw = _raw_config()
    if not raw:
        return False
    raw["notifications"] = {
        "telegram": True,
        "telegram_control": True,
        "tasks": bool(tasks),
        "errors": bool(errors),
        "system": bool(system),
    }
    return _save_config(raw)


def _send(token, chat, text):
    if not chat:
        chat = detect_chat_id(token)
    if not chat:
        log.info(
            "[NOTIFY] Telegram включён, но chat_id неизвестен. "
            "Отправьте боту /start и повторите."
        )
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000]},
            timeout=15,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("ok") is False:
            log.info(
                "[NOTIFY] Telegram отклонил сообщение: %s",
                data.get("description", "unknown"),
            )
            return False
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
    if not token:
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


def send_text(text, chat=""):
    """Синхронно отправляет текст в Telegram (для ответов бота)."""

    token, configured = _credentials()
    chat = str(chat or configured).strip()
    if not token:
        return False
    if not chat:
        chat = detect_chat_id(token)
    if not chat:
        return False
    return _send(token, chat, str(text or ""))


def send_test(text="✅ JARVIS: уведомления подключены."):
    """Отправляет тестовое сообщение и возвращает результат."""

    token, chat = _credentials()
    if not token:
        print("Нет telegram_bot_token в config.json или env.")
        return False
    if not chat:
        chat = detect_chat_id(token)
    if not chat:
        print(
            "chat_id не найден. Откройте бота в Telegram, нажмите "
            "Start (/start), затем повторите."
        )
        return False
    ok = _send(token, chat, text)
    print("Отправлено." if ok else "Не удалось отправить сообщение.")
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Проверка и настройка Telegram-уведомлений JARVIS."
    )
    parser.add_argument("--enable", action="store_true",
                        help="включить notifications в config.json")
    parser.add_argument("--detect", action="store_true",
                        help="найти chat_id по последним сообщениям бота")
    parser.add_argument("--test", action="store_true",
                        help="отправить тестовое сообщение")
    args = parser.parse_args(argv)

    token, chat = _credentials()
    section = _notifications_config()
    print(f"bot_token: {'есть' if token else 'нет'}")
    print(f"chat_id: {'есть' if chat else 'нет'}")
    print(f"telegram: {'включён' if section.get('telegram') else 'выключен'}")

    if args.enable:
        print("Включено." if enable() else "Не удалось изменить config.")
    if args.detect:
        found = detect_chat_id(token)
        print("chat_id найден." if found else "chat_id не найден.")
    if args.test:
        return 0 if send_test() else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
