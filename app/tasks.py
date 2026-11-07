import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.paths import DATA_DIR


class TaskManager:

    def __init__(self, path=None, max_tasks=200, max_workers=4):
        self.path = (
            Path(path)
            if path
            else DATA_DIR / "tasks.json"
        )
        self.max_tasks = max(10, int(max_tasks or 200))
        self._lock = threading.RLock()
        self._tasks = self._load()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="JARVIS-Task",
        )
        self._futures = {}

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    self._tasks,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError as error:
            print(f"[TASK SAVE ERROR] {error}")

    def _trim(self):
        if len(self._tasks) <= self.max_tasks:
            return
        ordered = sorted(
            self._tasks.values(),
            key=lambda item: item.get("created", ""),
            reverse=True,
        )
        keep = {
            item["id"]
            for item in ordered[: self.max_tasks]
        }
        self._tasks = {
            key: value
            for key, value in self._tasks.items()
            if key in keep
        }

    def create(self, title, kind="task", meta=None):
        task_id = uuid.uuid4().hex[:12]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "title": str(title or "Задача").strip(),
                "kind": str(kind or "task"),
                "status": "pending",
                "created": now,
                "updated": now,
                "steps": [],
                "result": "",
                "error": "",
                "meta": meta if isinstance(meta, dict) else {},
            }
            self._trim()
            self._save()
        return task_id

    def update(self, task_id, **fields):
        with self._lock:
            task = self._tasks.get(str(task_id))
            if task is None:
                return None
            task.update(fields)
            task["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save()
            return dict(task)

    def add_step(self, task_id, title, status="pending", detail=""):
        with self._lock:
            task = self._tasks.get(str(task_id))
            if task is None:
                return None
            task["steps"].append(
                {
                    "title": str(title),
                    "status": str(status),
                    "detail": str(detail),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            task["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save()
            return dict(task)

    def start(self, task_id):
        return self.update(task_id, status="running")

    def complete(self, task_id, result=""):
        return self.update(
            task_id,
            status="done",
            result=str(result or ""),
        )

    def fail(self, task_id, error=""):
        return self.update(
            task_id,
            status="failed",
            error=str(error or ""),
        )

    def cancel(self, task_id):
        task_id = str(task_id)
        future = self._futures.get(task_id)
        if future is not None:
            future.cancel()
        return self.update(task_id, status="cancelled")

    def cancel_all(self):
        with self._lock:
            ids = [
                task_id
                for task_id, task in self._tasks.items()
                if task.get("status") in {"pending", "running"}
            ]
        for task_id in ids:
            self.cancel(task_id)

    def get(self, task_id):
        with self._lock:
            task = self._tasks.get(str(task_id))
            return dict(task) if task else None

    def list(self, status=None, limit=50):
        with self._lock:
            items = list(self._tasks.values())
        if status:
            items = [
                item
                for item in items
                if item.get("status") == status
            ]
        items.sort(
            key=lambda item: item.get("created", ""),
            reverse=True,
        )
        return items[: max(1, int(limit or 50))]

    def run_background(self, title, func, *args, **kwargs):
        task_id = self.create(title, kind="background")
        self.start(task_id)

        def runner():
            try:
                result = func(*args, **kwargs)
                self.complete(task_id, result)
            except Exception as error:
                self.fail(
                    task_id,
                    f"{type(error).__name__}: {error}",
                )

        future = self._executor.submit(runner)
        self._futures[task_id] = future
        return task_id

    def summary(self, limit=20):
        items = self.list(limit=limit)
        if not items:
            return "Задач нет."
        lines = []
        for item in items:
            line = (
                f"{item['id']} [{item['status']}] "
                f"{item['title']}"
            )
            if item.get("result"):
                line += f" — {str(item['result'])[:160]}"
            if item.get("error"):
                line += f" — ошибка: {str(item['error'])[:160]}"
            lines.append(line)
        return "\n".join(lines)
