import atexit
import json
import threading
import time
import uuid
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.paths import DATA_DIR


def _flush_at_exit(ref):
    manager = ref()
    if manager is None:
        return
    try:
        manager.flush()
    except Exception:
        pass


class TaskManager:

    def __init__(
        self,
        path=None,
        max_tasks=200,
        max_workers=4,
        save_delay=0.75,
    ):
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
        self._save_delay = max(0.0, float(save_delay or 0.0))
        self._dirty = False
        self._last_write = 0.0
        self._save_timer = None
        atexit.register(_flush_at_exit, weakref.ref(self))

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

    def _write(self):
        """Пишет журнал на диск. Вызывается под self._lock."""
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
            # На Windows антивирус/индексатор иногда держит только что
            # созданный файл: повторяем replace пару раз вместо потери
            # последних шагов журнала.
            for attempt in range(3):
                try:
                    temp.replace(self.path)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.02)
        except OSError as error:
            print(f"[TASK SAVE ERROR] {error}")
            return False
        return True

    def _save(self, force=False):
        """Помечает журнал изменённым и пишет его не чаще save_delay.

        Раньше каждый add_step/update перезаписывал весь tasks.json;
        агентский цикл делал это десятки раз за один запуск. Теперь
        запись объединяется по времени, а force используется на
        финальных статусах.
        """

        self._dirty = True
        now = time.monotonic()
        elapsed = now - self._last_write
        if force or self._save_delay <= 0 or elapsed >= self._save_delay:
            if self._write():
                self._dirty = False
                self._last_write = now
            return
        timer = self._save_timer
        if timer is not None and timer.is_alive():
            return
        delay = max(0.01, self._save_delay - elapsed)
        timer = threading.Timer(delay, self._flush_from_timer)
        timer.daemon = True
        self._save_timer = timer
        timer.start()

    def _flush_from_timer(self):
        with self._lock:
            self._save_timer = None
            if not self._dirty:
                return
            if not self.path.parent.exists():
                # Каталог исчез (тесты/перенос) — не пересоздаём его.
                return
            if self._write():
                self._dirty = False
                self._last_write = time.monotonic()

    def flush(self):
        """Принудительно сохраняет журнал (границы задач, выход)."""

        with self._lock:
            timer = self._save_timer
            if timer is not None:
                timer.cancel()
                self._save_timer = None
            if not self._dirty:
                return
            if self._write():
                self._dirty = False
                self._last_write = time.monotonic()

    def shutdown(self):
        self.flush()
        self._executor.shutdown(wait=False, cancel_futures=True)

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

    def _notify_if_background(self, task, status, detail=""):
        if task and task.get("kind") == "background":
            try:
                from app import notifier

                notifier.notify_task(
                    task.get("title", "Задача"), status, detail
                )
            except Exception:
                pass

    def complete(self, task_id, result=""):
        task = self.update(
            task_id,
            status="done",
            result=str(result or ""),
        )
        self.flush()
        self._notify_if_background(task, "done", result)
        return task

    def fail(self, task_id, error=""):
        task = self.update(
            task_id,
            status="failed",
            error=str(error or ""),
        )
        self.flush()
        self._notify_if_background(task, "failed", error)
        return task

    def cancel(self, task_id):
        task_id = str(task_id)
        future = self._futures.get(task_id)
        if future is not None:
            future.cancel()
        task = self.update(task_id, status="cancelled")
        self.flush()
        self._notify_if_background(task, "cancelled")
        return task

    def cancel_all(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            ids = [
                task_id
                for task_id, task in self._tasks.items()
                if task.get("status") in {"pending", "running"}
            ]
            for task_id in ids:
                future = self._futures.get(task_id)
                if future is not None:
                    future.cancel()
                task = self._tasks.get(task_id)
                if task is not None:
                    task["status"] = "cancelled"
                    task["updated"] = now
            if ids:
                # Одна запись на всю пачку, а не по одной на задачу.
                self._save()
                self.flush()
            cancelled = [
                dict(self._tasks[task_id])
                for task_id in ids
                if task_id in self._tasks
            ]
        for task in cancelled:
            self._notify_if_background(task, "cancelled")

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

    def summary(self, limit=50):
        """Компактный список для UI: без шагов и метаданных.

        Полный список с шагами весил ~115 КБ на 50 задач и уходил
        в UI каждые 1.5 с; для карточек хватает этих полей.
        """

        items = self.list(limit=limit)
        result = []
        for item in items:
            result.append(
                {
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "kind": item.get("kind", "task"),
                    "status": item.get("status", ""),
                    "created": item.get("created", ""),
                    "updated": item.get("updated", ""),
                    "step_count": len(item.get("steps") or []),
                    "result": str(item.get("result") or "")[:160],
                    "error": str(item.get("error") or "")[:160],
                }
            )
        return result

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

    def describe(self, limit=20):
        """Текстовый список задач для инструмента list_tasks."""

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
