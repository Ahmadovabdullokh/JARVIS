import json
import re
import threading
import time
import uuid
from pathlib import Path

from app.paths import BASE_DIR

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|"
    r"bearer|cookie|session|private[_-]?key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s,;\"'}]+)"
)


def redact(text):
    return _SECRET_RE.sub(
        lambda match: match.group(1) + match.group(2) + "***",
        str(text or ""),
    )


class Trace:

    def __init__(
        self,
        logger,
        request_id,
        text,
        source="chat",
        mode="tasks",
    ):
        self.logger = logger
        self.id = request_id
        self.text = str(text or "")
        self.source = str(source or "chat")
        self.mode = str(mode or "tasks")
        self.started = time.time()

    def event(self, event, **payload):
        self.logger.write(
            {
                "type": "event",
                "request_id": self.id,
                "event": event,
                "mode": self.mode,
                "elapsed": round(time.time() - self.started, 3),
                **payload,
            }
        )

    def tool(self, name, arguments=None, result="", elapsed=0.0, ok=True):
        self.logger.write(
            {
                "type": "tool",
                "request_id": self.id,
                "name": str(name or ""),
                "mode": self.mode,
                "arguments": _compact(arguments),
                "result": redact(str(result or "")[:2000]),
                "elapsed": round(float(elapsed or 0), 3),
                "ok": bool(ok),
            }
        )

    def finish(self, answer="", status="ok"):
        self.logger.write(
            {
                "type": "finish",
                "request_id": self.id,
                "status": str(status or "ok"),
                "mode": self.mode,
                "elapsed": round(time.time() - self.started, 3),
                "answer": redact(str(answer or "")[:2000]),
                "source": self.source,
            }
        )


def _compact(value, limit=1000):
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return redact(text[:limit])


class TraceLogger:

    def __init__(self, path=None, max_bytes=5 * 1024 * 1024):
        self.path = (
            Path(path)
            if path
            else BASE_DIR / "data" / "traces.jsonl"
        )
        self.max_bytes = max(64 * 1024, int(max_bytes or 5 * 1024 * 1024))
        self._lock = threading.Lock()

    def _rotate(self):
        try:
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                backup = self.path.with_suffix(".1")
                if backup.exists():
                    backup.unlink()
                self.path.replace(backup)
        except OSError:
            pass

    def write(self, record):
        payload = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **record,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._rotate()
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )
        except OSError as error:
            print(f"[TRACE ERROR] {error}")

    def start(self, text, source="chat", mode="tasks"):
        trace = Trace(
            self,
            uuid.uuid4().hex[:12],
            text,
            source=source,
            mode=mode,
        )
        trace.event("start", text=redact(str(text or "")[:2000]))
        return trace

    def tail(self, limit=40):
        if not self.path.exists():
            return "Журнал трассировки пуст."
        lines = self.path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        return "\n".join(lines[-max(1, int(limit or 40)):]) or (
            "Журнал трассировки пуст."
        )

    def clear(self):
        with self._lock:
            for path in (
                self.path,
                self.path.with_suffix(".1"),
            ):
                if path.exists():
                    path.unlink()
        return "Журнал трассировки очищен."


_TRACER = None


def tracer():
    global _TRACER
    if _TRACER is None:
        _TRACER = TraceLogger()
    return _TRACER
