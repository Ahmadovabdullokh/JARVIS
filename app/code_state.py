import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from app.paths import DATA_DIR
from app.safety import redact_secrets

CONTINUATION_PREFIXES = (
    "продолж",
    "continue",
    "дальше",
    "доделай",
    "заверши",
)


class CodeAgentState:
    """Состояние кодовой задачи: план, правки и проверки."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DATA_DIR / "code_state.json"
        self.backup_dir = self.path.parent / "code_backups"
        self._lock = threading.RLock()
        self._publisher = None
        self.task_id = uuid.uuid4().hex[:12]
        self.session_id = ""
        self.goal = ""
        self.project = ""
        self.status = "idle"
        self.plan = []
        self.files_read = {}
        self.changed_files = []
        self.backups = []
        self.checks = []
        self.verified = False
        self.active = False
        self.revision = 0
        self.created = self._now()
        self.updated = self.created
        self._load()

    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%dT%H:%M:%S")

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for name in (
            "task_id",
            "session_id",
            "goal",
            "project",
            "status",
            "created",
            "updated",
        ):
            value = data.get(name)
            if isinstance(value, str):
                setattr(self, name, value)
        for name in ("plan", "changed_files", "backups", "checks"):
            value = data.get(name)
            if isinstance(value, list):
                setattr(self, name, value)
        files_read = data.get("files_read")
        if isinstance(files_read, dict):
            self.files_read = {
                str(key): str(value)
                for key, value in files_read.items()
            }
        self.verified = bool(data.get("verified", False))
        self.active = False
        self.revision = int(data.get("revision", 0) or 0)

    def _save(self):
        payload = self.snapshot(include_active=True)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            pass
        self._publish(payload)

    def set_publisher(self, publisher):
        self._publisher = publisher

    def _publish(self, payload):
        if self._publisher is None:
            return
        try:
            self._publisher(payload)
        except Exception:
            pass

    def snapshot(self, include_active=False):
        with self._lock:
            data = {
                "task_id": self.task_id,
                "session_id": self.session_id,
                "goal": redact_secrets(self.goal),
                "project": self.project,
                "status": self.status,
                "plan": [
                    {
                        **item,
                        "step": redact_secrets(item.get("step", "")),
                        "note": redact_secrets(item.get("note", "")),
                    }
                    for item in self.plan
                ],
                "changed_files": list(self.changed_files),
                "checks": [dict(item) for item in self.checks],
                "verified": bool(self.verified),
                "revision": int(self.revision),
                "backups": len(self.backups),
                "read_files": len(self.files_read),
                "updated": self.updated,
            }
            if include_active:
                data["active"] = bool(self.active)
            return data

    def begin_task(self, goal, project, session_id=""):
        goal_text = str(goal or "").strip()
        with self._lock:
            continuation = bool(self.goal) and goal_text.lower().startswith(
                CONTINUATION_PREFIXES
            )
            if not continuation:
                self.task_id = uuid.uuid4().hex[:12]
                self.plan = []
                self.files_read = {}
                self.changed_files = []
                self.backups = []
                self.checks = []
                self.verified = False
                self.status = "planning"
            else:
                self.status = "running"
            self.goal = goal_text
            self.project = str(project or "").strip()
            self.session_id = str(session_id or "")
            self.active = True
            self.created = self._now()
            self.updated = self.created
            self.revision += 1
            self._save()

    def finish(self, status="done"):
        with self._lock:
            self.active = False
            self.status = str(status or "done")
            self.updated = self._now()
            self.revision += 1
            self._save()

    def set_status(self, status):
        with self._lock:
            self.status = str(status or self.status)
            self.updated = self._now()
            self.revision += 1
            self._save()

    def set_plan(self, steps):
        normalized = []
        for item in steps or []:
            if isinstance(item, dict):
                text = str(
                    item.get("step")
                    or item.get("title")
                    or item.get("text")
                    or ""
                ).strip()
                status = str(item.get("status") or "pending").strip()
                note = str(item.get("note") or "").strip()
            else:
                text = str(item or "").strip()
                status = "pending"
                note = ""
            if not text:
                continue
            if status not in {
                "pending",
                "running",
                "done",
                "failed",
                "blocked",
            }:
                status = "pending"
            normalized.append(
                {
                    "step": text[:500],
                    "status": status,
                    "note": note[:500],
                }
            )
        with self._lock:
            self.plan = normalized
            self.status = "running" if normalized else "planning"
            self.updated = self._now()
            self.revision += 1
            self._save()
        return self.plan_text()

    def update_plan_step(self, step, status="done", note=""):
        try:
            index = int(step) - 1
        except (TypeError, ValueError):
            return "Ошибка: номер шага должен быть числом."
        with self._lock:
            if index < 0 or index >= len(self.plan):
                return f"Ошибка: шага {step} нет в плане."
            if status not in {
                "pending",
                "running",
                "done",
                "failed",
                "blocked",
            }:
                status = "done"
            self.plan[index]["status"] = status
            if note:
                self.plan[index]["note"] = str(note)[:500]
            self.updated = self._now()
            self.revision += 1
            self._save()
        return self.plan_text()

    def plan_text(self):
        if not self.plan:
            return "План пуст."
        labels = {
            "pending": "[ ]",
            "running": "[~]",
            "done": "[x]",
            "failed": "[!]",
            "blocked": "[#]",
        }
        lines = []
        for index, item in enumerate(self.plan, start=1):
            line = (
                f"{index}. {labels.get(item.get('status'), '[ ]')} "
                f"{item.get('step', '')}"
            )
            note = str(item.get("note") or "").strip()
            if note:
                line += f" — {note}"
            lines.append(line)
        return "\n".join(lines)

    def mark_read(self, path):
        with self._lock:
            self.files_read[self._key(path)] = self._now()
            self.revision += 1

    def has_read(self, path):
        with self._lock:
            return self._key(path) in self.files_read

    @staticmethod
    def _key(path):
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(path)

    def mark_changed(self, path, backup=None, existed=None):
        key = self._key(path)
        with self._lock:
            if key not in self.changed_files:
                self.changed_files.append(key)
            if backup is not None and not any(
                item.get("path") == key for item in self.backups
            ):
                self.backups.append(
                    {
                        "path": key,
                        "backup": str(backup or ""),
                        "existed": bool(existed),
                    }
                )
            self.verified = False
            self.updated = self._now()
            self.revision += 1
            self._save()

    def backup_file(self, path):
        target = Path(path)
        key = self._key(target)
        with self._lock:
            if any(item.get("path") == key for item in self.backups):
                return None
            existed = target.exists()
            backup = ""
            if existed and target.is_file():
                folder = self.backup_dir / self.task_id
                folder.mkdir(parents=True, exist_ok=True)
                backup_path = folder / (
                    f"{uuid.uuid4().hex[:8]}_{target.name}"
                )
                try:
                    shutil.copy2(target, backup_path)
                    backup = str(backup_path)
                except OSError:
                    backup = ""
            return {
                "path": key,
                "backup": backup,
                "existed": existed,
            }

    def record_check(self, name, ok, detail="", mark_verified=False):
        with self._lock:
            self.checks.append(
                {
                    "name": str(name or "check"),
                    "ok": bool(ok),
                    "detail": str(detail or "")[:4000],
                    "at": self._now(),
                }
            )
            if mark_verified:
                self.verified = bool(ok)
            self.updated = self._now()
            self.revision += 1
            self._save()

    def rollback(self):
        with self._lock:
            messages = []
            for item in reversed(self.backups):
                target = Path(item.get("path", ""))
                backup = Path(item.get("backup", "")) if item.get("backup") else None
                if backup is not None and backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    shutil.copy2(backup, target)
                    messages.append(f"Восстановлен: {target}")
                elif not item.get("existed") and target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                    messages.append(f"Удалён созданный файл: {target}")
                else:
                    messages.append(f"Нет резервной копии: {target}")
            self.changed_files = []
            self.backups = []
            self.checks = []
            self.verified = False
            self.status = "rolled_back"
            self.updated = self._now()
            self.revision += 1
            self._save()
        return "\n".join(messages) or "Нечего откатывать."

    def prompt(self, max_chars=5000):
        with self._lock:
            plan = redact_secrets(self.plan_text())
            changed = (
                ", ".join(Path(item).name for item in self.changed_files)
                or "нет"
            )
            checks = "\n".join(
                f"- {'OK' if item.get('ok') else 'FAIL'} "
                f"{item.get('name')}: {item.get('detail', '')[:300]}"
                for item in self.checks[-5:]
            ) or "проверок ещё не было"
            text = (
                "СОСТОЯНИЕ КОДОВОЙ ЗАДАЧИ\n"
                f"Цель: {redact_secrets(self.goal) or 'не задана'}\n"
                f"Проект: {self.project or 'не задан'}\n"
                f"Статус: {self.status}\n"
                f"План:\n{plan}\n"
                f"Изменённые файлы: {changed}\n"
                f"Проверки:\n{checks}\n"
                "Правило: не завершай задачу, пока code_verify не пройден."
            )
            return text[:max_chars]
