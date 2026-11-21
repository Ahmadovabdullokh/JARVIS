"""Управление JARVIS из Telegram: приём команд и ответы в чат.

Работает через long polling getUpdates, поэтому webhook не нужен.
Разрешён только chat_id из config.json (integrations.telegram_chat_id);
сообщения из других чатов игнорируются.

Включается в config.json:

    "notifications": {
        "telegram": true,
        "telegram_control": true
    }
"""

import json
import os
import threading

import requests

from app import config as config_module
from app import notifier
from app.logging import get_logger
from app.paths import CONFIG_FILE, DATA_DIR, ensure_runtime_dirs

log = get_logger(__name__)

OFFSET_FILE = DATA_DIR / "telegram_offset.json"
LOCK_FILE = DATA_DIR / "telegram_bot.lock"

_stop = threading.Event()
_thread = None
_lock_handle = None
_offset = 0

HELP = (
    "JARVIS на связи.\n\n"
    "Команды:\n"
    "/status — состояние и режим\n"
    "/mode chat|tasks|code — сменить режим\n"
    "/stop — аварийная остановка\n"
    "/id — chat_id\n\n"
    "Любой другой текст — обычный запрос к JARVIS."
)


def _settings():
    raw = {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    section = raw.get("notifications")
    return section if isinstance(section, dict) else {}


def _enabled():
    section = _settings()
    return bool(section.get("telegram")) and bool(
        section.get("telegram_control", True)
    )


def _load_offset():
    try:
        data = json.loads(OFFSET_FILE.read_text(encoding="utf-8"))
        return int(data.get("offset", 0))
    except (OSError, ValueError):
        return 0


def _save_offset(value):
    global _offset
    _offset = int(value)
    try:
        OFFSET_FILE.write_text(
            json.dumps({"offset": _offset}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _acquire_lock():
    global _lock_handle
    ensure_runtime_dirs()
    handle = LOCK_FILE.open("a+")
    try:
        handle.seek(0)
        if handle.read(1) == "":
            handle.write(" ")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_handle = handle
    return True


def _release_lock():
    global _lock_handle
    handle = _lock_handle
    _lock_handle = None
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


def _allowed_chat(token=""):
    _, chat = notifier._credentials()
    if chat:
        return chat
    return notifier.detect_chat_id(token)


def _save_chat(chat_id):
    raw = notifier._raw_config()
    if not raw:
        return
    integrations = raw.setdefault("integrations", {})
    if not isinstance(integrations, dict):
        integrations = {}
        raw["integrations"] = integrations
    integrations["telegram_chat_id"] = str(chat_id)
    config_module.save_config(raw)


def _reply(chat_id, text):
    text = str(text or "").strip()
    if not text:
        return False
    ok = True
    for start in range(0, len(text), 4000):
        ok = notifier.send_text(text[start:start + 4000], chat_id) and ok
    return ok


def _status_text():
    from app.main import get_chat_mode, get_task_snapshot
    from app.status import get_status

    tasks = get_task_snapshot() or []
    active = [
        item for item in tasks
        if item.get("status") in {"pending", "running"}
    ]
    return (
        f"Статус: {get_status()}\n"
        f"Режим: {get_chat_mode()}\n"
        f"Активных задач: {len(active)} из {len(tasks)}"
    )


def _handle_text(chat_id, text):
    from app.main import (
        get_chat_mode,
        set_chat_mode,
        stop_assistant,
        submit_chat_message,
    )

    lowered = text.lower().strip()
    if lowered in {"/start", "/help", "start", "help", "/?"}:
        _reply(chat_id, HELP)
        return
    if lowered == "/id" or lowered == "id":
        _reply(chat_id, f"chat_id: {chat_id}")
        return
    if lowered == "/status" or lowered == "статус":
        _reply(chat_id, _status_text())
        return
    if lowered == "/stop" or lowered == "стоп":
        stop_assistant(emergency=True)
        _reply(chat_id, "🛑 Аварийная остановка выполнена.")
        return
    if lowered.startswith("/mode") or lowered.startswith("режим"):
        parts = text.replace("/", " ").split()
        if len(parts) < 2 or parts[1].lower() not in {
            "chat", "tasks", "code"
        }:
            _reply(chat_id, "Использование: /mode chat|tasks|code")
            return
        mode = set_chat_mode(parts[1].lower())
        _reply(chat_id, f"Режим: {mode}")
        return
    if lowered.startswith("/chat "):
        text = text[6:].strip()
    elif lowered.startswith("/"):
        _reply(chat_id, HELP)
        return

    mode = get_chat_mode()
    accepted = submit_chat_message(
        text,
        mode=mode,
        on_reply=lambda answer: _reply(chat_id, answer),
    )
    if not accepted:
        _reply(chat_id, "Не удалось принять сообщение.")


def _handle_update(update):
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id or not text:
        return

    token, configured = notifier._credentials()
    allowed = configured or _allowed_chat(token)
    if allowed and chat_id != str(allowed):
        log.info("[TELEGRAM] Игнорирую чат %s (не владелец).", chat_id)
        return
    if not allowed:
        _save_chat(chat_id)
        allowed = chat_id
        _reply(chat_id, "Чат привязан к JARVIS.\n\n" + HELP)
        return

    log.info("[TELEGRAM] Команда из чата %s: %s", chat_id, text[:200])
    try:
        _handle_text(chat_id, text)
    except Exception as error:
        log.info(
            f"[TELEGRAM] Ошибка обработки: "
            f"{type(error).__name__}: {error}"
        )
        _reply(chat_id, f"Ошибка: {type(error).__name__}: {error}")


def _loop(token):
    offset = _load_offset()
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    while not _stop.is_set():
        try:
            response = requests.get(
                url,
                params={
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": '["message"]',
                },
                timeout=35,
            )
            data = response.json()
        except Exception as error:
            log.info(
                f"[TELEGRAM] getUpdates: "
                f"{type(error).__name__}: {error}"
            )
            _stop.wait(5)
            continue

        if not data.get("ok"):
            description = str(data.get("description") or "")
            log.info("[TELEGRAM] getUpdates отклонён: %s", description)
            _stop.wait(10)
            continue

        for update in data.get("result") or []:
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            _save_offset(offset)
            _handle_update(update)


def start():
    """Запускает фоновый приём команд Telegram (один раз на процесс)."""

    global _thread
    if _thread is not None and _thread.is_alive():
        return True
    if not _enabled():
        return False

    token, _ = notifier._credentials()
    if not token:
        return False
    if not _acquire_lock():
        log.info("[TELEGRAM] Бот уже запущен в другом процессе.")
        return False

    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(token,),
        name="JARVIS-Telegram",
        daemon=True,
    )
    _thread.start()
    log.info("[TELEGRAM] Управление ботом запущено.")
    return True


def stop():
    global _thread
    _stop.set()
    thread = _thread
    _thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=3)
    _release_lock()
