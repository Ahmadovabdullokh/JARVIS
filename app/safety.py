import ctypes
import json
import re
import threading
import time
from pathlib import Path

from app.paths import BASE_DIR

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|"
    r"bearer|cookie|session|private[_-]?key)",
    re.IGNORECASE,
)

SECRET_VALUE_RES = (
    re.compile(r"\b(gsk_[A-Za-z0-9_\-]{10,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{10,})\b"),
    re.compile(r"\b(Bearer\s+)[A-Za-z0-9._\-]{10,}", re.IGNORECASE),
)

SECRET_KV_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|"
    r"bearer|cookie|session|private[_-]?key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s,;\"'}]+)"
)


class SafetyManager:

    def __init__(self, config=None, base_dir=None):
        config = config if isinstance(config, dict) else {}
        safety = config.get("safety", {})
        if not isinstance(safety, dict):
            safety = {}
        agent = config.get("agent", {})
        if not isinstance(agent, dict):
            agent = {}

        self.base_dir = Path(base_dir) if base_dir else BASE_DIR
        self.autonomy = str(
            safety.get("autonomy", agent.get("autonomy", "full"))
        ).strip().lower()
        if self.autonomy not in {"safe", "balanced", "full"}:
            self.autonomy = "full"

        self.confirm_destructive = bool(
            safety.get("confirm_destructive", False)
        )
        self.redact_secrets = bool(
            safety.get("redact_secrets", True)
        )
        self.dry_run = bool(safety.get("dry_run", False))
        self.max_output_chars = int(
            safety.get(
                "max_output_chars",
                agent.get("tool_result_limit", 12000),
            )
        )
        self.emergency_hotkey = str(
            safety.get("emergency_hotkey", "<ctrl>+<alt>+j")
        )
        self.audit_path = Path(
            safety.get("audit_log", "data/audit.log")
        )
        if not self.audit_path.is_absolute():
            self.audit_path = self.base_dir / self.audit_path
        self.tool_policies = safety.get("tool_policies", {})
        if not isinstance(self.tool_policies, dict):
            self.tool_policies = {}
        self.taint_tracking = bool(
            safety.get("taint_tracking", True)
        )
        self.audit_max_bytes = int(
            safety.get("audit_max_bytes", 2 * 1024 * 1024)
        )

        self._session_allow = {
            str(item)
            for item in safety.get("session_allow", [])
            if str(item).strip()
        }
        self._session_deny = {
            str(item)
            for item in safety.get("session_deny", [])
            if str(item).strip()
        }
        self._untrusted_sources = set()
        self._confirm_handler = None

        self.stop_event = threading.Event()
        self._audit_lock = threading.Lock()
        self._last_confirmation = {}
        self._hotkey_listener = None

    def stop(self):
        self.stop_event.set()

    def resume(self):
        self.stop_event.clear()

    def start_hotkey_listener(self, on_stop=None):
        if self._hotkey_listener is not None:
            return (
                f"Аварийный стоп уже слушает "
                f"{self.emergency_hotkey}."
            )
        try:
            from pynput import keyboard
        except Exception as error:
            return f"Глобальная горячая клавиша недоступна: {error}"

        def callback():
            self.stop()
            if on_stop is not None:
                try:
                    on_stop()
                except Exception:
                    pass

        try:
            listener = keyboard.GlobalHotKeys(
                {self.emergency_hotkey: callback}
            )
            listener.daemon = True
            listener.start()
        except Exception as error:
            return f"Не удалось включить горячую клавишу: {error}"

        self._hotkey_listener = listener
        return f"Аварийный стоп: {self.emergency_hotkey}"

    def stop_hotkey_listener(self):
        if self._hotkey_listener is None:
            return
        try:
            self._hotkey_listener.stop()
        except Exception:
            pass
        self._hotkey_listener = None

    def set_confirm_handler(self, handler):
        self._confirm_handler = handler

    def allow_session(self, name):
        name = str(name or "").strip()
        if name:
            self._session_allow.add(name)
            self._session_deny.discard(name)

    def deny_session(self, name):
        name = str(name or "").strip()
        if name:
            self._session_deny.add(name)
            self._session_allow.discard(name)

    def reset_session_policies(self):
        self._session_allow.clear()
        self._session_deny.clear()

    def mark_untrusted(self, source):
        source = str(source or "").strip()
        if source:
            self._untrusted_sources.add(source)

    def clear_untrusted(self):
        self._untrusted_sources.clear()

    def untrusted_sources(self):
        return sorted(self._untrusted_sources)

    def _policy_for(self, spec):
        for key in (spec.name, spec.category):
            value = self.tool_policies.get(key)
            if value is not None:
                return str(value).strip().lower()
        return ""

    def confirm(self, action, reason=""):
        prompt = str(action or "Выполнить действие?")
        reason = str(reason or "").strip()
        if reason:
            prompt += f"\n\n{reason}"
        prompt += "\n\nПодтвердить?"

        if self._confirm_handler is not None:
            try:
                return bool(self._confirm_handler(action, reason, prompt))
            except Exception as error:
                print(f"[CONFIRM ERROR] {error}")
                return False

        try:
            result = ctypes.windll.user32.MessageBoxW(
                None,
                prompt,
                "Подтверждение JARVIS",
                0x00000004 | 0x00000030 | 0x00040000,
            )
            return result == 6
        except Exception:
            print(f"[CONFIRM] {prompt}")
            try:
                answer = input("Подтвердить? [y/N]: ").strip().lower()
            except EOFError:
                return False
            return answer in {"y", "yes", "д", "да"}

    def before_tool(self, spec, arguments):
        if self.stop_event.is_set():
            return "Выполнение остановлено пользователем."

        policy = self._policy_for(spec)
        if policy in {"deny", "forbidden", "block"}:
            self._audit(
                event="denied",
                tool=spec.name,
                category=spec.category,
                danger=spec.danger,
                arguments=arguments,
                result=f"POLICY:{policy}",
            )
            return (
                f"Инструмент {spec.name} запрещён политикой "
                f"безопасности."
            )

        if spec.name in self._session_deny:
            return f"Инструмент {spec.name} запрещён в этой сессии."

        if (
            self.dry_run
            and spec.danger != "safe"
            and policy != "allow"
        ):
            self._audit(
                event="dry_run",
                tool=spec.name,
                category=spec.category,
                danger=spec.danger,
                arguments=arguments,
                result="DRY-RUN",
            )
            return (
                f"[DRY-RUN] {spec.name} не выполнен. "
                f"Аргументы: {self.redact(json.dumps(arguments, ensure_ascii=False, default=str))}"
            )

        needs_confirmation = False
        taint_reason = ""

        if policy == "confirm":
            needs_confirmation = True
        elif policy == "allow" or spec.name in self._session_allow:
            needs_confirmation = False
        elif self.autonomy == "safe":
            needs_confirmation = True
        elif self.autonomy == "balanced":
            needs_confirmation = spec.danger in {"confirm", "dangerous"}
        elif self.autonomy == "full":
            needs_confirmation = (
                self.confirm_destructive
                and spec.danger == "dangerous"
            )

        if (
            self.taint_tracking
            and self._untrusted_sources
            and spec.danger in {"confirm", "dangerous"}
            and spec.name not in self._session_allow
            and policy != "allow"
        ):
            needs_confirmation = True
            taint_reason = (
                "Обнаружен недоверенный контент из источников: "
                + ", ".join(sorted(self._untrusted_sources))
            )

        if needs_confirmation:
            action = f"Инструмент: {spec.name}\n{spec.description}"
            reason = json.dumps(arguments, ensure_ascii=False, default=str)
            if taint_reason:
                reason += f"\n\n{taint_reason}"
            if not self.confirm(action, reason):
                self._audit(
                    event="cancelled",
                    tool=spec.name,
                    category=spec.category,
                    danger=spec.danger,
                    arguments=arguments,
                    result="USER_CANCELLED",
                )
                return False

        self._audit(
            event="start",
            tool=spec.name,
            category=spec.category,
            danger=spec.danger,
            arguments=arguments,
        )
        return True

    def after_tool(self, spec, arguments, result, elapsed):
        if (
            spec.danger in {"confirm", "dangerous"}
            and self._untrusted_sources
            and not str(result).startswith(("Ошибка", "Таймаут"))
        ):
            self.clear_untrusted()
        result = self.redact(str(result))
        if (
            self.max_output_chars > 0
            and len(result) > self.max_output_chars
        ):
            result = (
                result[: self.max_output_chars]
                + "\n…[вывод обрезан]"
            )

        self._audit(
            event="finish",
            tool=spec.name,
            category=spec.category,
            danger=spec.danger,
            arguments=arguments,
            elapsed=round(elapsed, 3),
            result=result[:2000],
        )
        return result

    def redact(self, text):
        text = str(text or "")
        if not self.redact_secrets:
            return text

        text = SECRET_KV_RE.sub(
            lambda match: match.group(1) + match.group(2) + "***",
            text,
        )

        for pattern in SECRET_VALUE_RES:
            if pattern.groups:
                text = pattern.sub(
                    lambda match: (
                        match.group(1) + "***"
                        if match.lastindex
                        else "***"
                    ),
                    text,
                )
            else:
                text = pattern.sub("***", text)

        return text

    def _rotate_audit(self):
        if self.audit_max_bytes <= 0:
            return
        try:
            if (
                self.audit_path.exists()
                and self.audit_path.stat().st_size
                >= self.audit_max_bytes
            ):
                backup = self.audit_path.with_suffix(
                    self.audit_path.suffix + ".1"
                )
                if backup.exists():
                    backup.unlink()
                self.audit_path.replace(backup)
        except OSError:
            pass

    def _audit(self, **record):
        payload = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(),
            ),
            **record,
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
            )
            with self._audit_lock:
                self._rotate_audit()
                with self.audit_path.open(
                    "a",
                    encoding="utf-8",
                ) as file:
                    file.write(self.redact(line) + "\n")
        except Exception as error:
            print(f"[AUDIT ERROR] {error}")

    def tail_audit(self, limit=50):
        try:
            lines = self.audit_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return "Журнал аудита пуст."

        limit = max(1, min(int(limit or 50), 500))
        return "\n".join(lines[-limit:]) or "Журнал аудита пуст."
