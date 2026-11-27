import os
import threading
import time

from app import config as config_module
from app import i18n, performance, persona, telemetry, ui_theme
from app.camera_service import (
    QUALITY_PRESETS,
    get_camera_service,
    load_camera_settings,
)
from app.camera_service import probe_cameras as probe_pc_cameras
from app.doctor import format_report, run_checks
from app.gestures import get_gesture_service, load_gesture_settings
from app.logging import get_logger
from app.main import (
    camera_look as describe_camera_frame,
)
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
from app.tools import get_plugin_manager

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
        self._remote_url = ""

    def attach_remote(self, server):
        """Запоминает адрес remote-сервера для абсолютных ссылок HUD."""

        self._remote_url = str(getattr(server, "url", "") or "")

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
        threading.Thread(
            target=self._autostart_media,
            name="JARVIS-MediaAutostart",
            daemon=True,
        ).start()
        if start_backend:
            self._backend_thread = threading.Thread(
                target=self._run_backend,
                name="JARVIS-Main",
                daemon=True,
            )
            self._backend_thread.start()
            self._backend_started = True

    def _autostart_media(self):
        try:
            camera_config = load_camera_settings()
            gesture_config = load_gesture_settings()
            if not (
                camera_config.get("enabled")
                or gesture_config.get("enabled")
            ):
                return
            # Источник «телефон» включается приложением: на старте ПК
            # нечего ждать, иначе HUD висит в ожидании кадров.
            if camera_config.get("source") == "phone":
                camera_config["enabled"] = False
            camera = get_camera_service()
            if camera_config.get("enabled") and not camera.is_running():
                camera.start(camera_config)
            if gesture_config.get("enabled"):
                get_gesture_service().start(gesture_config)
        except Exception as error:
            log.info(
                f"[MEDIA] Автозапуск не удался: "
                f"{type(error).__name__}: {error}"
            )

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
            self._mic_stop.wait(performance.mic_interval(0.3))

    def shutdown(self):
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        self._mic_stop.set()
        try:
            get_gesture_service().stop()
        except Exception:
            pass
        try:
            get_camera_service().stop()
        except Exception:
            pass
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

        try:
            data["camera"] = get_camera_service().status()
            data["gesture"] = get_gesture_service().status()
        except Exception as error:
            data["camera"] = {"running": False, "error": str(error)}
            data["gesture"] = {"running": False, "error": str(error)}

        return data

    def bootstrap(self):
        with self._lock:
            catalog = _json_safe(self._catalog)
        data = self._snapshot(force=True)
        config = config_module.read_config_file()
        try:
            i18n.set_language(config.get("language"))
        except Exception:
            pass
        manager = get_plugin_manager()
        data.update(
            {
                "catalog": catalog,
                "settings": self.settings_payload(),
                "palette": self.palette(),
                "greeting": persona.get_time_greeting(),
                "version": "MK X",
                "language": i18n.get_language(),
                "languages": i18n.available_languages(),
                "plugins": (
                    _json_safe(manager.loaded_plugins())
                    if manager is not None
                    else []
                ),
                "profiles": {
                    "active": config_module.get_active_profile(config),
                    "names": config_module.profile_names(config),
                },
                "performance": performance.bootstrap_payload(),
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
            "language": str(config.get("language", "ru")),
            "active_profile": config_module.get_active_profile(config),
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

        language = payload.get("language")
        if language is not None:
            config["language"] = i18n.set_language(language)

        config_module.save_config(config)
        if language is not None:
            i18n.set_language(config["language"])
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

    def list_plugins(self):
        manager = get_plugin_manager()
        if manager is None:
            return {"plugins": [], "errors": [], "report": "Плагины недоступны."}
        return {
            "plugins": _json_safe(manager.loaded_plugins()),
            "errors": [
                {"name": name, "error": error}
                for name, error in manager.errors
            ],
            "report": manager.report(),
        }

    def reload_plugins(self):
        manager = get_plugin_manager()
        if manager is None:
            raise ValueError("Менеджер плагинов недоступен.")
        loaded = manager.reload()
        publish_ui_event("system", i18n.t("plugins.reloaded"))
        return {"loaded": loaded, "report": manager.report()}

    def get_profiles(self):
        config = config_module.read_config_file()
        return {
            "active": config_module.get_active_profile(config),
            "names": config_module.profile_names(config),
            "profiles": _json_safe(config_module.get_profiles(config)),
        }

    def set_profile(self, payload):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("Не указано имя профиля.")
        config = config_module.read_config_file()
        if name not in config_module.get_profiles(config):
            raise ValueError(f"Профиль «{name}» не найден.")
        updated = config_module.apply_profile(config, name)
        config_module.save_config(updated)
        publish_ui_event(
            "system",
            i18n.t("profile.changed", name=name),
        )
        return {"active": name}

    def set_language(self, payload):
        config = config_module.read_config_file()
        code = i18n.set_language(payload.get("language"))
        if config:
            config["language"] = code
            config_module.save_config(config)
        return {"language": code}

    # ------------------------------------------------------------------
    # Камера и жесты
    # ------------------------------------------------------------------

    def camera_stream_url(self):
        camera = get_camera_service()
        base = (self._remote_url or "http://127.0.0.1:8765").rstrip("/")
        return f"{base}/camera.mjpg?token={camera.stream_token}"

    def get_camera(self):
        return {
            "camera": get_camera_service().status(),
            "gesture": get_gesture_service().status(),
            "quality_presets": sorted(QUALITY_PRESETS),
            "stream_url": self.camera_stream_url(),
        }

    def get_camera_stream_url(self):
        return {"url": self.camera_stream_url()}

    def get_pairing(self, consumer="default"):
        """Ссылка и QR для подключения телефона (только локально).

        Токен в ссылке — секрет, поэтому удалённому клиенту метод
        недоступен: remote_server отклоняет его до вызова моста.
        """

        if consumer == "remote":
            raise ValueError("QR-код подключения доступен только на ПК.")
        from app import pairing

        return pairing.pairing_payload(ensure_topic=True)

    def camera_look(self, payload):
        """Описывает текущий кадр камеры через vision-модель Groq."""

        question = str(payload.get("question") or "").strip()
        return describe_camera_frame(question)

    def _save_camera_config(self, updates):
        config = config_module.read_config_file()
        if not config:
            return
        section = config.get("camera")
        section = section if isinstance(section, dict) else {}
        section.update(updates)
        config["camera"] = section
        config_module.save_config(config)

    def _save_gesture_config(self, updates):
        config = config_module.read_config_file()
        if not config:
            return
        section = config.get("gestures")
        section = section if isinstance(section, dict) else {}
        section.update(updates)
        config["gestures"] = section
        config_module.save_config(config)

    def set_camera(self, payload):
        camera = get_camera_service()
        gesture = get_gesture_service()
        enabled = bool(payload.get("enabled", True))
        if not enabled:
            gesture.stop()
            camera.stop()
            self._save_camera_config({"enabled": False})
            return self.get_camera()

        settings = load_camera_settings()
        for key in (
            "source",
            "index",
            "url",
            "width",
            "height",
            "fps",
            "stream_fps",
            "ingest_fps",
            "analyze_fps",
            "jpeg_quality",
            "mirror",
            "backend",
            "fourcc",
            "quality",
            "sharpness",
            "upscale",
            "background",
            "immersive",
            "fit",
            "phone_timeout",
            "phone_auto_switch",
        ):
            if key in payload:
                settings[key] = payload[key]
        settings["enabled"] = True
        source = settings.get("source")
        if source == "network" and not settings.get("url"):
            raise ValueError("Для сетевой камеры нужен URL потока.")
        if source == "phone":
            # Телефон отдаёт уже готовый кадр: зеркало по умолчанию
            # выключено, иначе задняя камера показывается отражённой.
            settings["url"] = ""
            if "mirror" not in payload:
                settings["mirror"] = False
        camera.start(settings)
        self._save_camera_config(
            {key: settings[key] for key in settings if key != "enabled"}
            | {"enabled": True}
        )
        if source == "phone":
            # Android не вызывает set_gestures: если жесты включены
            # в конфиге, возвращаем их после переключения на телефон.
            gesture_config = load_gesture_settings()
            if gesture_config.get("enabled"):
                try:
                    if not gesture.status().get("running"):
                        gesture.start(gesture_config)
                except Exception as error:
                    log.info(
                        "[CAMERA] Жесты не запустились: %s: %s",
                        type(error).__name__,
                        error,
                    )
        return self.get_camera()

    def set_gestures(self, payload):
        gesture = get_gesture_service()
        enabled = bool(payload.get("enabled", True))
        if not enabled:
            gesture.stop()
            self._save_gesture_config({"enabled": False})
            return self.get_camera()

        camera = get_camera_service()
        if not camera.is_running():
            settings = load_camera_settings()
            settings["enabled"] = True
            camera.start(settings)
            self._save_camera_config({"enabled": True})
        gesture.start()
        profile = payload.get("profile")
        if profile:
            try:
                gesture.set_profile(profile)
                self._save_gesture_config({"profile": str(profile)})
            except ValueError:
                pass
        if "pointer" in payload:
            try:
                gesture.set_pointer(bool(payload.get("pointer")))
            except Exception:
                pass
        self._save_gesture_config({"enabled": True})
        return self.get_camera()

    def set_camera_quality(self, payload):
        quality = str(payload.get("quality") or "balanced").strip().lower()
        if quality not in QUALITY_PRESETS and quality != "custom":
            raise ValueError(f"Неизвестный пресет качества: {quality}")
        camera = get_camera_service()
        camera.set_quality(quality)
        self._save_camera_config({"quality": quality})
        return self.get_camera()

    def set_camera_background(self, payload):
        enabled = bool(payload.get("enabled", True))
        immersive = payload.get("immersive")
        updates = {"background": enabled}
        if immersive is not None:
            updates["immersive"] = bool(immersive)
        get_camera_service().update_settings(updates)
        self._save_camera_config(updates)
        return self.get_camera()

    def set_gestures_profile(self, payload):
        name = str(payload.get("profile") or "").strip().lower()
        if not name:
            raise ValueError("Не указан профиль жестов.")
        gesture = get_gesture_service()
        gesture.set_profile(name)
        pointer_enabled = name == "pointer"
        if pointer_enabled:
            gesture.set_pointer(True)
        config = config_module.read_config_file()
        section = config.get("gestures")
        section = section if isinstance(section, dict) else {}
        section["profile"] = name
        pointer = section.get("pointer")
        pointer = pointer if isinstance(pointer, dict) else {}
        pointer["enabled"] = pointer_enabled
        section["pointer"] = pointer
        config["gestures"] = section
        config_module.save_config(config)
        return self.get_camera()

    def set_pointer(self, payload):
        enabled = bool(payload.get("enabled", True))
        gesture = get_gesture_service()
        gesture.set_pointer(enabled)
        config = config_module.read_config_file()
        section = config.get("gestures")
        section = section if isinstance(section, dict) else {}
        pointer = section.get("pointer")
        pointer = pointer if isinstance(pointer, dict) else {}
        pointer["enabled"] = enabled
        section["pointer"] = pointer
        if enabled:
            section["profile"] = "pointer"
        config["gestures"] = section
        config_module.save_config(config)
        return self.get_camera()

    def probe_cameras(self):
        settings = load_camera_settings()
        cameras = probe_pc_cameras(
            width=settings.get("width", 640),
            height=settings.get("height", 480),
            fps=settings.get("fps", 30),
            backend=settings.get("backend", "auto"),
        )
        return {
            "cameras": cameras,
            "camera": get_camera_service().status(),
        }

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
            "list_plugins": lambda: self.list_plugins(),
            "reload_plugins": lambda: self.reload_plugins(),
            "get_profiles": lambda: self.get_profiles(),
            "set_profile": lambda: self.set_profile(payload),
            "set_language": lambda: self.set_language(payload),
            "get_camera": lambda: self.get_camera(),
            "get_camera_stream_url": lambda: self.get_camera_stream_url(),
            "get_pairing": lambda: self.get_pairing(consumer),
            "camera_look": lambda: self.camera_look(payload),
            "set_camera": lambda: self.set_camera(payload),
            "set_camera_quality": lambda: self.set_camera_quality(payload),
            "set_camera_background": lambda: self.set_camera_background(
                payload
            ),
            "probe_cameras": lambda: self.probe_cameras(),
            "set_gestures": lambda: self.set_gestures(payload),
            "set_gestures_profile": lambda: self.set_gestures_profile(
                payload
            ),
            "set_pointer": lambda: self.set_pointer(payload),
        }
        handler = handlers.get(str(method))
        if handler is None:
            raise ValueError(f"Неизвестный метод: {method}")
        return handler()
