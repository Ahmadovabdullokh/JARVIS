import os
import threading
import time

from app import config as config_module
from app import persona, telemetry, ui_theme
from app.doctor import format_report, run_checks
from app.logging import get_logger
from app.main import (
    cancel_task,
    drain_ui_events,
    get_chat_mode,
    get_listener,
    get_task_snapshot,
    microphone_enabled,
    publish_ui_event,
    set_chat_mode,
    set_microphone_enabled,
    set_speak_text,
    set_transcript_preview,
    stop_assistant,
    submit_chat_message,
    transcript_preview_enabled,
)
from app.main import main as run_assistant
from app.observability import tracer
from app.paths import CONFIG_FILE, DATA_DIR
from app.status import get_status, set_status

log = get_logger(__name__)

STATUS_TEXT = {
    "mic_off": ("MIC OFF", "Микрофон выключен — можно печатать."),
    "starting": ("STARTING", "Запуск подсистем…"),
    "ready": ("READY", "Ожидаю команду…"),
    "listening": ("LISTENING", "Слушаю команду…"),
    "processing": ("PROCESSING", "Распознаю речь…"),
    "thinking": ("THINKING", "Анализирую запрос…"),
    "speaking": ("SPEAKING", "Говорю…"),
    "error": ("ERROR", "Требуется внимание."),
    "stopped": ("OFFLINE", "Система остановлена."),
}

AUTONOMY_LEVELS = ("safe", "balanced", "full")
CHAT_MODES = ("chat", "tasks", "code")


def _json_safe(value, limit=8000):
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item, limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, limit) for item in value]
    return _json_safe(str(value), limit)


def _section(config, name):
    value = config.get(name)
    return value if isinstance(value, dict) else {}


class UiBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._cursor_lock = threading.Lock()
        self._catalog = []
        self._started = False
        self._shutdown_done = False
        self._backend_started = False
        self._mic_stop = threading.Event()
        self._mic_thread = None
        self._backend_thread = None
        self._mic_level = 0.0
        self._last_status = 0.0
        self._last_telemetry = 0.0
        self._last_tasks = 0.0
        self._last_mic = 0.0
        self._started_at = time.monotonic()
        self._event_cursors = {}

    def start(self, start_backend=True):
        with self._lock:
            if self._started:
                return
            self._started = True
        self._mic_thread = threading.Thread(
            target=self._mic_loop,
            name="JARVIS-MicMeter",
            daemon=True,
        )
        self._mic_thread.start()
        if start_backend:
            self._backend_thread = threading.Thread(
                target=self._run_backend,
                name="JARVIS-Main",
                daemon=True,
            )
            self._backend_thread.start()
            self._backend_started = True

    def _run_backend(self):
        try:
            run_assistant()
        except Exception as error:
            log.info(
                f"[WEB LAUNCHER] {type(error).__name__}: {error}"
            )
            set_status("error")
            publish_ui_event(
                "error",
                f"JARVIS не смог запуститься: {error}",
            )
            try:
                from app import notifier

                notifier.notify(
                    f"❌ JARVIS не смог запуститься: {error}",
                    kind="errors",
                )
            except Exception:
                pass
        finally:
            set_status("stopped")
            publish_ui_event("system", "JARVIS завершил работу.")

    def _mic_loop(self):
        while not self._mic_stop.is_set():
            level = 0.0
            listener = get_listener()
            if listener is not None and get_status() in {
                "listening",
                "ready",
            }:
                try:
                    level = listener.measure_level(0.15)
                except Exception:
                    level = 0.0
            self._mic_level = max(0.0, float(level))
            self._mic_stop.wait(0.3)

    def shutdown(self):
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        self._mic_stop.set()
        try:
            stop_assistant()
        except Exception:
            pass

    def _snapshot(self, force=False):
        now = time.monotonic()
        data = {
            "server_time": time.time(),
            "chat_mode": get_chat_mode(),
            "transcript_preview": transcript_preview_enabled(),
            "mic_enabled": microphone_enabled(),
            "uptime_seconds": round(now - self._started_at, 1),
        }

        if force or now - self._last_status >= 0.1:
            status = get_status()
            label, description = STATUS_TEXT.get(
                status,
                ("ONLINE", "Активен."),
            )
            data["status"] = {
                "name": status,
                "label": label,
                "description": description,
            }
            self._last_status = now

        if force or now - self._last_telemetry >= 2.0:
            data["telemetry"] = telemetry.snapshot()
            self._last_telemetry = now

        if force or now - self._last_tasks >= 1.5:
            data["tasks"] = _json_safe(get_task_snapshot())
            self._last_tasks = now

        if force or now - self._last_mic >= 0.1:
            data["mic"] = round(self._mic_level, 4)
            self._last_mic = now

        return data

    def bootstrap(self):
        with self._lock:
            catalog = _json_safe(self._catalog)
        data = self._snapshot(force=True)
        data.update(
            {
                "catalog": catalog,
                "settings": self.settings_payload(),
                "palette": self.palette(),
                "greeting": persona.get_time_greeting(),
                "version": "MK IX",
            }
        )
        return data

    def poll(self, consumer="default"):
        with self._cursor_lock:
            cursor = self._event_cursors.get(consumer, 0)
        latest = cursor
        events = []
        for seq, event_type, payload in drain_ui_events(cursor):
            latest = max(latest, seq)
            if event_type == "command_catalog":
                with self._lock:
                    self._catalog = _json_safe(payload)
            events.append(
                {
                    "type": event_type,
                    "payload": _json_safe(payload),
                    "ts": time.time(),
                }
            )
        with self._cursor_lock:
            self._event_cursors[consumer] = latest
        return {
            "events": events,
            "snapshot": self._snapshot(),
        }

    def settings_payload(self):
        config = config_module.read_config_file()
        agent = _section(config, "agent")
        safety = _section(config, "safety")
        return {
            "autonomy": str(
                agent.get("autonomy")
                or safety.get("autonomy")
                or "balanced"
            ),
            "confirm_destructive": bool(
                safety.get("confirm_destructive", True)
            ),
            "dry_run": bool(safety.get("dry_run", False)),
            "taint_tracking": bool(
                safety.get("taint_tracking", True)
            ),
            "transcript_preview": bool(
                config.get("transcript_preview", False)
            ),
            "speak_text": bool(config.get("speak_text", True)),
            "category_planning": bool(
                agent.get("category_planning", True)
            ),
            "max_tools_per_request": int(
                agent.get("max_tools_per_request", 100)
            ),
            "code_tools_per_request": int(
                agent.get("code_tools_per_request", 28)
            ),
            "max_iterations": int(agent.get("max_iterations", 12)),
            "max_tokens": int(agent.get("max_tokens", 3000)),
            "tool_timeout_seconds": int(
                agent.get("tool_timeout_seconds", 120)
            ),
            "stt_noise_adapt_k": float(
                config.get("stt_noise_adapt_k", 3.0)
            ),
            "max_speech_seconds": float(
                config.get("max_speech_seconds", 12.0)
            ),
            "silence_duration": float(
                config.get("silence_duration", 0.7)
            ),
            "chat_mode": str(config.get("chat_mode", "tasks")),
        }

    def palette(self):
        return {
            "bg": ui_theme.BG,
            "panel": ui_theme.PANEL,
            "panel_alt": ui_theme.PANEL_ALT,
            "card": ui_theme.CARD,
            "border": ui_theme.BORDER,
            "text": ui_theme.TEXT,
            "muted": ui_theme.MUTED,
            "accent": ui_theme.ACCENT,
            "accent_soft": ui_theme.ACCENT_SOFT,
            "accent_dark": ui_theme.ACCENT_DARK,
            "violet": ui_theme.VIOLET,
            "error": ui_theme.ERROR,
            "warning": ui_theme.WARNING,
            "success": ui_theme.SUCCESS,
        }

    def save_settings(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Некорректные настройки.")

        config = config_module.read_config_file()
        if not config:
            raise ValueError("Не удалось прочитать config.")

        agent = config.setdefault("agent", {})
        safety = config.setdefault("safety", {})
        if not isinstance(agent, dict):
            agent = {}
            config["agent"] = agent
        if not isinstance(safety, dict):
            safety = {}
            config["safety"] = safety

        autonomy = str(
            payload.get("autonomy", agent.get("autonomy", "balanced"))
        ).lower()
        if autonomy not in AUTONOMY_LEVELS:
            raise ValueError("Недопустимый уровень автономности.")

        chat_mode = str(
            payload.get("chat_mode", config.get("chat_mode", "tasks"))
        ).lower()
        if chat_mode not in CHAT_MODES:
            chat_mode = "tasks"

        def as_int(key, default, minimum=0):
            try:
                value = int(payload.get(key, default))
            except (TypeError, ValueError) as error:
                raise ValueError(f"{key}: ожидалось целое число.") from error
            return max(minimum, value)

        def as_float(key, default, minimum=0.0):
            try:
                value = float(payload.get(key, default))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{key}: ожидалось число."
                ) from error
            return max(minimum, value)

        agent["autonomy"] = autonomy
        safety["autonomy"] = autonomy
        safety["confirm_destructive"] = bool(
            payload.get("confirm_destructive", False)
        )
        safety["dry_run"] = bool(payload.get("dry_run", False))
        safety["taint_tracking"] = bool(
            payload.get("taint_tracking", True)
        )
        config["transcript_preview"] = bool(
            payload.get("transcript_preview", False)
        )
        config["speak_text"] = bool(
            payload.get("speak_text", True)
        )
        agent["category_planning"] = bool(
            payload.get("category_planning", True)
        )
        agent["max_tools_per_request"] = as_int(
            "max_tools_per_request",
            100,
            1,
        )
        agent["code_tools_per_request"] = as_int(
            "code_tools_per_request",
            28,
            1,
        )
        agent["max_iterations"] = as_int("max_iterations", 12, 1)
        agent["max_tokens"] = as_int("max_tokens", 3000, 256)
        agent["tool_timeout_seconds"] = as_int(
            "tool_timeout_seconds",
            120,
            5,
        )
        config["stt_noise_adapt_k"] = as_float(
            "stt_noise_adapt_k",
            3.0,
            1.0,
        )
        config["max_speech_seconds"] = as_float(
            "max_speech_seconds",
            12.0,
            1.0,
        )
        config["silence_duration"] = as_float(
            "silence_duration",
            0.7,
            0.1,
        )
        config["chat_mode"] = chat_mode

        config_module.save_config(config)
        set_chat_mode(chat_mode)
        set_transcript_preview(
            bool(payload.get("transcript_preview", False))
        )
        set_speak_text(bool(payload.get("speak_text", True)))
        publish_ui_event(
            "system",
            "Настройки сохранены. Изменения применятся после "
            "перезапуска JARVIS.",
        )
        return {"message": "Настройки сохранены."}

    def send_message(self, payload):
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("Пустое сообщение.")
        mode = str(payload.get("mode") or get_chat_mode()).lower()
        if mode not in CHAT_MODES:
            mode = get_chat_mode()
        if not submit_chat_message(text, mode=mode):
            raise ValueError("Сообщение не было отправлено.")
        return {"accepted": True}

    def stop(self):
        stop_assistant(emergency=True)
        publish_ui_event(
            "system",
            "Аварийная остановка: инструменты и задачи остановлены.",
        )
        return {"stopped": True}

    def cancel_task(self, payload):
        task_id = str(payload.get("id") or "").strip()
        if not task_id:
            raise ValueError("Некорректный ID задачи.")
        if not cancel_task(task_id):
            raise ValueError("Не удалось отменить задачу.")
        return {"cancelled": True, "id": task_id}

    def set_mode(self, payload):
        mode = str(payload.get("mode", "tasks")).lower()
        if mode not in CHAT_MODES:
            raise ValueError("Недопустимый режим.")
        return {"mode": set_chat_mode(mode)}

    def set_preview(self, payload):
        enabled = bool(payload.get("enabled", False))
        set_transcript_preview(enabled)
        return {"enabled": enabled}

    def set_microphone(self, payload):
        enabled = payload.get("enabled")
        if enabled is None:
            enabled = not microphone_enabled()
        return {"enabled": set_microphone_enabled(bool(enabled))}

    def get_catalog(self):
        with self._lock:
            return {"tools": _json_safe(self._catalog)}

    def get_journal(self, payload):
        limit = int(payload.get("lines", 300))
        limit = max(1, min(2000, limit))
        return {"text": tracer().tail(limit)}

    def get_audit(self, payload):
        limit = int(payload.get("lines", 200))
        limit = max(1, min(2000, limit))
        path = DATA_DIR / "audit.log"
        if not path.exists():
            return {"text": "Журнал аудита пуст."}
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        return {"text": "\n".join(lines[-limit:])}

    def run_doctor(self):
        def worker():
            try:
                report = format_report(run_checks())
            except Exception as error:
                report = f"Диагностика не удалась: {error}"
            publish_ui_event("system", report)

        threading.Thread(
            target=worker,
            name="JARVIS-Doctor",
            daemon=True,
        ).start()
        return {"started": True}

    def open_path(self, payload):
        kind = str(payload.get("kind", "")).lower()
        paths = {
            "config": CONFIG_FILE,
            "audit": DATA_DIR / "audit.log",
            "data": DATA_DIR,
        }
        path = paths.get(kind)
        if path is None:
            raise ValueError("Неизвестный путь.")
        if not path.exists():
            raise ValueError("Файл или каталог не найден.")
        os.startfile(str(path))
        return {"opened": str(path)}

    def client_event(self, payload):
        kind = str(payload.get("kind", "event"))
        message = str(payload.get("message", ""))[:1000]
        log.info(f"[WEB CLIENT] {kind}: {message}")
        return {"ok": True}

    def handle(self, method, payload=None, consumer="default"):
        payload = payload if isinstance(payload, dict) else {}
        handlers = {
            "bootstrap": lambda: self.bootstrap(),
            "client_ready": lambda: self.client_event(
                {"kind": "ready", "message": "UI initialized"}
            ),
            "client_error": lambda: self.client_event(payload),
            "poll": lambda: self.poll(consumer),
            "send_message": lambda: self.send_message(payload),
            "stop": lambda: self.stop(),
            "cancel_task": lambda: self.cancel_task(payload),
            "set_mode": lambda: self.set_mode(payload),
            "set_preview": lambda: self.set_preview(payload),
            "set_microphone": lambda: self.set_microphone(payload),
            "get_catalog": lambda: self.get_catalog(),
            "get_journal": lambda: self.get_journal(payload),
            "get_audit": lambda: self.get_audit(payload),
            "run_doctor": lambda: self.run_doctor(),
            "save_settings": lambda: self.save_settings(payload),
            "open_path": lambda: self.open_path(payload),
        }
        handler = handlers.get(str(method))
        if handler is None:
            raise ValueError(f"Неизвестный метод: {method}")
        return handler()
