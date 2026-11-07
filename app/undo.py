import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from app.paths import DATA_DIR


class UndoJournal:

    def __init__(self, path=None, backup_dir=None):
        self.path = (
            Path(path)
            if path
            else DATA_DIR / "undo" / "journal.jsonl"
        )
        self.backup_dir = (
            Path(backup_dir)
            if backup_dir
            else self.path.parent / "backups"
        )
        self._lock = threading.RLock()

    def _append(self, record):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record["id"] = uuid.uuid4().hex[:12]
        record["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(record, ensure_ascii=False, default=str)
                    + "\n"
                )
        return record

    def _records(self):
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def _write_records(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(
                    json.dumps(record, ensure_ascii=False, default=str)
                    + "\n"
                )
        temp.replace(self.path)

    def _backup(self, path):
        path = Path(path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / (
            f"{int(time.time() * 1000)}_"
            f"{uuid.uuid4().hex[:8]}_{path.name}"
        )
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        return target

    def _move_to_backup(self, path):
        path = Path(path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / (
            f"{int(time.time() * 1000)}_"
            f"{uuid.uuid4().hex[:8]}_{path.name}"
        )
        shutil.move(str(path), str(target))
        return target

    def record_write(self, path):
        path = Path(path)
        backup = ""
        existed = path.exists()
        if existed and path.is_file():
            try:
                backup = str(self._backup(path))
            except OSError as error:
                print(f"[UNDO BACKUP ERROR] {error}")
        return self._append(
            {
                "op": "write",
                "path": str(path),
                "backup": backup,
                "existed": existed,
            }
        )

    def record_delete(self, path):
        path = Path(path)
        backup = self._move_to_backup(path)
        return self._append(
            {
                "op": "delete",
                "path": str(path),
                "backup": str(backup),
            }
        )

    def record_move(self, source, destination):
        source = Path(source)
        destination = Path(destination)
        destination_backup = ""
        if destination.exists():
            destination_backup = str(self._backup(destination))
        return self._append(
            {
                "op": "move",
                "source": str(source),
                "destination": str(destination),
                "destination_backup": destination_backup,
            }
        )

    def record_copy(self, destination):
        return self._append(
            {
                "op": "copy",
                "destination": str(Path(destination)),
            }
        )

    def record_created(self, path):
        return self._append(
            {
                "op": "created",
                "path": str(Path(path)),
            }
        )

    def list(self, limit=20):
        records = self._records()
        return list(reversed(records[-max(1, int(limit or 20)):]))

    def undo_last(self):
        with self._lock:
            records = self._records()
            if not records:
                return "Журнал отмены пуст."
            record = records[-1]
            try:
                message = self._undo(record)
            except Exception as error:
                return f"Не удалось отменить действие: {error}"
            self._write_records(records[:-1])
            return message

    def undo_all(self):
        messages = []
        while True:
            message = self.undo_last()
            if message in {"Журнал отмены пуст.",}:
                break
            messages.append(message)
            if len(messages) >= 100:
                break
        return "\n".join(messages) or "Журнал отмены пуст."

    def clear(self):
        with self._lock:
            if self.path.exists():
                self.path.unlink()
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir, ignore_errors=True)
        return "Журнал отмены очищен."

    def _undo(self, record):
        op = record.get("op")
        if op == "write":
            path = Path(record.get("path", ""))
            backup = record.get("backup") or ""
            if backup and Path(backup).exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                if Path(backup).is_dir():
                    shutil.copytree(Path(backup), path)
                else:
                    shutil.copy2(Path(backup), path)
                return f"Восстановлена предыдущая версия: {path}"
            if path.exists() and not record.get("existed"):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return f"Удалён созданный файл: {path}"
            return f"Нечего восстанавливать для: {path}"

        if op == "delete":
            path = Path(record.get("path", ""))
            backup = record.get("backup") or ""
            if not backup or not Path(backup).exists():
                return f"Резервная копия не найдена: {path}"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            shutil.move(str(backup), str(path))
            return f"Восстановлено из удаления: {path}"

        if op == "move":
            source = Path(record.get("source", ""))
            destination = Path(record.get("destination", ""))
            backup = record.get("destination_backup") or ""
            if source.exists():
                return f"Источник уже существует: {source}"
            source.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.move(str(destination), str(source))
            if backup and Path(backup).exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                if Path(backup).is_dir():
                    shutil.copytree(Path(backup), destination)
                else:
                    shutil.copy2(Path(backup), destination)
            return f"Перемещение отменено: {destination} -> {source}"

        if op == "copy":
            destination = Path(record.get("destination", ""))
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
                return f"Удалена копия: {destination}"
            return f"Копия уже отсутствует: {destination}"

        if op == "created":
            path = Path(record.get("path", ""))
            if not path.exists():
                return f"Уже отсутствует: {path}"
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    return f"Папка не пуста, не удалена: {path}"
            else:
                path.unlink()
            return f"Удалён созданный объект: {path}"

        return f"Неизвестная операция отмены: {op}"

    def summary(self, limit=20):
        records = self.list(limit=limit)
        if not records:
            return "Журнал отмены пуст."
        lines = []
        for record in records:
            op = record.get("op", "?")
            target = (
                record.get("path")
                or record.get("destination")
                or record.get("source")
                or ""
            )
            lines.append(
                f"{record.get('at', '')} [{op}] {target} "
                f"({record.get('id', '')})"
            )
        return "\n".join(lines)


_JOURNAL = None


def journal():
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = UndoJournal()
    return _JOURNAL
