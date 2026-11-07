import csv
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path

from app.tools.common import (
    BASE_DIR,
    human_size,
    optional_import,
    powershell,
    resolve_path,
    run_command,
)
from app.undo import journal


def _iter_files(root, limit=200):
    count = 0
    for path in root.rglob("*"):
        if path.is_file():
            yield path
            count += 1
            if count >= limit:
                return


def _hash_file(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register(registry):

    @registry.tool(
        "files_list",
        "Показать содержимое папки с размерами и датами.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="files",
    )
    def files_list(path, recursive=False, pattern=None, limit=300):
        root = resolve_path(path, must_exist=True)
        if not root.is_dir():
            return f"Это не папка: {root}"
        items = []
        iterator = root.rglob(pattern or "*") if recursive else root.glob(pattern or "*")
        for item in iterator:
            try:
                info = item.stat()
                items.append(
                    (
                        item,
                        info.st_size if item.is_file() else 0,
                        info.st_mtime,
                    )
                )
            except OSError:
                continue
            if len(items) >= max(1, int(limit or 300)):
                break
        if not items:
            return "Папка пуста или ничего не найдено."
        lines = [f"Содержимое {root}:"]
        for item, size, mtime in items:
            kind = "DIR " if item.is_dir() else "FILE"
            lines.append(
                f"{kind} {item.name} | {human_size(size)} | "
                f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}"
            )
        return "\n".join(lines)

    @registry.tool(
        "files_search",
        "Найти файлы по имени, маске или содержимому.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "root": {"type": "string"},
                "content": {"type": "boolean"},
                "regex": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="files",
    )
    def files_search(query, root=None, content=False, regex=False, limit=50):
        query = str(query or "").strip()
        if not query:
            return "Пустой поисковый запрос."
        roots = [resolve_path(root)] if root else [
            Path.home() / "Desktop",
            Path.home() / "Downloads",
            Path.home() / "Documents",
        ]
        limit = max(1, min(int(limit or 50), 500))
        found = []
        import re as re_module

        pattern = re_module.compile(
            query if regex else re_module.escape(query),
            re_module.IGNORECASE,
        ) if (content or regex) else None

        for base in roots:
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                matched = False
                if pattern is not None:
                    if content:
                        try:
                            text = path.read_text(
                                encoding="utf-8",
                                errors="ignore",
                            )
                            matched = bool(pattern.search(text))
                        except OSError:
                            matched = False
                    if not matched:
                        matched = bool(pattern.search(path.name))
                else:
                    matched = query.lower() in path.name.lower()
                if matched:
                    found.append(str(path))
                    if len(found) >= limit:
                        break
            if len(found) >= limit:
                break
        if not found:
            return f"Ничего не найдено по запросу «{query}»."
        return "Найдено:\n" + "\n".join(found)

    @registry.tool(
        "file_read",
        "Прочитать текстовый файл.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="files",
    )
    def file_read(path, encoding="utf-8", max_chars=20000):
        file_path = resolve_path(path, must_exist=True)
        if file_path.is_dir():
            return "Это папка, а не файл."
        text = file_path.read_text(
            encoding=encoding or "utf-8",
            errors="replace",
        )
        max_chars = max(100, int(max_chars or 20000))
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[файл обрезан]"
        return text

    @registry.tool(
        "file_write",
        "Записать или перезаписать текстовый файл.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "encoding": {"type": "string"},
                "append": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
        category="files",
        danger="confirm",
    )
    def file_write(path, content, encoding="utf-8", append=False):
        file_path = resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(file_path)
        mode = "a" if append else "w"
        with file_path.open(mode, encoding=encoding or "utf-8") as file:
            file.write(str(content))
        return f"Записано: {file_path} ({human_size(file_path.stat().st_size)})"

    @registry.tool(
        "file_append",
        "Дописать текст в конец файла.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "encoding": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        category="files",
        danger="confirm",
    )
    def file_append(path, content, encoding="utf-8"):
        return file_write(path, content, encoding=encoding, append=True)

    @registry.tool(
        "directory_create",
        "Создать папку, включая вложенные.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
        danger="confirm",
    )
    def directory_create(path):
        target = resolve_path(path)
        if not target.exists():
            journal().record_created(target)
        target.mkdir(parents=True, exist_ok=True)
        return f"Папка создана: {target}"

    @registry.tool(
        "path_delete",
        "Удалить файл или папку. По умолчанию в корзину; permanent — через журнал отмены.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "permanent": {"type": "boolean"},
            },
            "required": ["path"],
        },
        category="files",
        danger="dangerous",
    )
    def path_delete(path, permanent=False):
        target = resolve_path(path, must_exist=True)
        if permanent:
            journal().record_delete(target)
            return (
                f"Удалено с возможностью отмены: {target}. "
                f"Восстановить: undo_last."
            )
        send2trash = optional_import("send2trash")
        if send2trash is not None:
            send2trash.send2trash(str(target))
            return f"Перемещено в корзину: {target}"
        journal().record_delete(target)
        return (
            f"Удалено с возможностью отмены: {target} "
            f"(корзина недоступна)."
        )

    @registry.tool(
        "path_copy",
        "Скопировать файл или папку.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["source", "destination"],
        },
        category="files",
        danger="confirm",
    )
    def path_copy(source, destination, overwrite=False):
        src = resolve_path(source, must_exist=True)
        dst = resolve_path(destination)
        if src == dst:
            return "Источник и назначение совпадают."
        if dst.exists() and not overwrite:
            return f"Назначение уже существует: {dst}"
        if dst.exists() and overwrite:
            journal().record_write(dst)
        if src.is_dir():
            if dst.exists() and overwrite:
                shutil.rmtree(dst)
            shutil.copytree(src, dst, dirs_exist_ok=overwrite)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        journal().record_copy(dst)
        return f"Скопировано: {src} -> {dst}"

    @registry.tool(
        "path_move",
        "Переместить или переименовать файл/папку.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["source", "destination"],
        },
        category="files",
        danger="confirm",
    )
    def path_move(source, destination, overwrite=False):
        src = resolve_path(source, must_exist=True)
        dst = resolve_path(destination)
        if src == dst:
            return "Источник и назначение совпадают."
        if dst.exists() and not overwrite:
            return f"Назначение уже существует: {dst}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        journal().record_move(src, dst)
        if dst.exists() and overwrite:
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
        return f"Перемещено: {src} -> {dst}"

    @registry.tool(
        "path_rename",
        "Переименовать файл или папку в той же папке.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "new_name": {"type": "string"},
            },
            "required": ["path", "new_name"],
        },
        category="files",
        danger="confirm",
    )
    def path_rename(path, new_name):
        src = resolve_path(path, must_exist=True)
        new_name = str(new_name or "").strip()
        if not new_name or any(char in new_name for char in "\\/"):
            return "Некорректное новое имя."
        if new_name == src.name:
            return "Имя не изменилось."
        dst = src.with_name(new_name)
        if dst.exists():
            return f"Имя уже занято: {dst}"
        journal().record_move(src, dst)
        src.rename(dst)
        return f"Переименовано: {src.name} -> {dst.name}"

    @registry.tool(
        "file_info",
        "Показать подробную информацию о файле или папке.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
    )
    def file_info(path):
        target = resolve_path(path, must_exist=True)
        info = target.stat()
        return (
            f"Путь: {target}\n"
            f"Тип: {'папка' if target.is_dir() else 'файл'}\n"
            f"Размер: {human_size(info.st_size)}\n"
            f"Создан: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.st_ctime))}\n"
            f"Изменён: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.st_mtime))}\n"
            f"Атрибуты: {stat.filemode(info.st_mode)}"
        )

    @registry.tool(
        "file_hash",
        "Вычислить хеш файла.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "algorithm": {"type": "string"},
            },
            "required": ["path"],
        },
        category="files",
    )
    def file_hash(path, algorithm="sha256"):
        target = resolve_path(path, must_exist=True)
        if not target.is_file():
            return "Хеш можно вычислить только для файла."
        return f"{algorithm}: {_hash_file(target, algorithm or 'sha256')}"

    @registry.tool(
        "files_compare",
        "Сравнить два файла по хешу и размеру.",
        {
            "type": "object",
            "properties": {
                "first": {"type": "string"},
                "second": {"type": "string"},
            },
            "required": ["first", "second"],
        },
        category="files",
    )
    def files_compare(first, second):
        one = resolve_path(first, must_exist=True)
        two = resolve_path(second, must_exist=True)
        same = (
            one.stat().st_size == two.stat().st_size
            and _hash_file(one) == _hash_file(two)
        )
        return "Файлы идентичны." if same else "Файлы различаются."

    @registry.tool(
        "files_duplicates",
        "Найти дубликаты файлов в папке.",
        {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["root"],
        },
        category="files",
    )
    def files_duplicates(root, limit=50):
        base = resolve_path(root, must_exist=True)
        groups = {}
        for path in _iter_files(base, limit=5000):
            try:
                key = (path.stat().st_size, _hash_file(path))
            except OSError:
                continue
            groups.setdefault(key, []).append(str(path))
        duplicates = [
            items for items in groups.values() if len(items) > 1
        ][: max(1, int(limit or 50))]
        if not duplicates:
            return "Дубликатов не найдено."
        return "\n\n".join(
            "Дубликаты:\n" + "\n".join(items)
            for items in duplicates
        )

    @registry.tool(
        "archive_create",
        "Создать zip-архив из файлов или папки.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "archive": {"type": "string"},
            },
            "required": ["source", "archive"],
        },
        category="files",
        danger="confirm",
    )
    def archive_create(source, archive):
        src = resolve_path(source, must_exist=True)
        dst = resolve_path(archive)
        dst.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(dst)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            if src.is_dir():
                for path in src.rglob("*"):
                    if path.is_file():
                        zf.write(path, path.relative_to(src.parent))
            else:
                zf.write(src, src.name)
        return f"Архив создан: {dst} ({human_size(dst.stat().st_size)})"

    @registry.tool(
        "archive_extract",
        "Распаковать zip-архив.",
        {
            "type": "object",
            "properties": {
                "archive": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["archive", "destination"],
        },
        category="files",
        danger="confirm",
    )
    def archive_extract(archive, destination):
        src = resolve_path(archive, must_exist=True)
        dst = resolve_path(destination)
        dst.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            for name in zf.namelist():
                target = dst / name
                if target.exists() and target.is_file():
                    journal().record_write(target)
            zf.extractall(dst)
        for path in dst.rglob("*"):
            if path.is_file():
                journal().record_created(path)
        return f"Распаковано в {dst}"

    @registry.tool(
        "disk_usage",
        "Показать занятое и свободное место на диске.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
        category="files",
    )
    def disk_usage(path=None):
        target = resolve_path(path or Path.home().anchor)
        usage = shutil.disk_usage(target)
        return (
            f"Диск {target}: всего {human_size(usage.total)}, "
            f"занято {human_size(usage.used)}, "
            f"свободно {human_size(usage.free)}."
        )

    @registry.tool(
        "drives_list",
        "Показать все доступные диски.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        category="files",
    )
    def drives_list():
        drives = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = Path(f"{letter}:\\")
            if path.exists():
                try:
                    usage = shutil.disk_usage(path)
                    drives.append(
                        f"{letter}: {human_size(usage.free)} свободно"
                    )
                except OSError:
                    drives.append(f"{letter}:")
        return "Диски:\n" + "\n".join(drives) if drives else "Диски не найдены."

    @registry.tool(
        "path_open",
        "Открыть файл или папку в проводнике/приложении по умолчанию.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
    )
    def path_open(path):
        target = resolve_path(path, must_exist=True)
        os.startfile(str(target))
        return f"Открыл: {target}"

    @registry.tool(
        "path_reveal",
        "Показать файл или папку в проводнике.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
    )
    def path_reveal(path):
        target = resolve_path(path, must_exist=True)
        if target.is_dir():
            os.startfile(str(target))
        else:
            run_command(["explorer.exe", "/select,", str(target)], timeout=10)
        return f"Показал в проводнике: {target}"

    @registry.tool(
        "temp_cleanup",
        "Очистить временные файлы пользователя и Windows.",
        {
            "type": "object",
            "properties": {"dry_run": {"type": "boolean"}},
            "required": [],
        },
        category="files",
        danger="confirm",
    )
    def temp_cleanup(dry_run=False):
        targets = [
            Path(tempfile.gettempdir()),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Temp",
            Path(os.environ.get("WINDIR", "C:\\Windows")) / "Temp",
        ]
        removed = 0
        errors = 0
        for root in targets:
            if not root.exists():
                continue
            for path in root.iterdir():
                try:
                    if path.is_dir():
                        if not dry_run:
                            shutil.rmtree(path)
                    else:
                        if not dry_run:
                            path.unlink()
                    removed += 1
                except OSError:
                    errors += 1
        prefix = "[DRY-RUN] " if dry_run else ""
        return (
            f"{prefix}Обработано объектов: {removed}, "
            f"ошибок: {errors}."
        )

    @registry.tool(
        "recent_files",
        "Показать недавно изменённые файлы в папке.",
        {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "days": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="files",
    )
    def recent_files(root=None, days=7, limit=50):
        base = resolve_path(root or Path.home())
        threshold = time.time() - max(1, int(days or 7)) * 86400
        items = []
        for path in _iter_files(base, limit=5000):
            try:
                if path.stat().st_mtime >= threshold:
                    items.append(path)
            except OSError:
                continue
        items.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        items = items[: max(1, int(limit or 50))]
        if not items:
            return "Недавних файлов не найдено."
        return "\n".join(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(item.stat().st_mtime))} "
            f"{item}"
            for item in items
        )

    @registry.tool(
        "files_bulk_rename",
        "Массово переименовать файлы по шаблону.",
        {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "pattern": {"type": "string"},
                "template": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["root", "pattern", "template"],
        },
        category="files",
        danger="confirm",
    )
    def files_bulk_rename(root, pattern, template, dry_run=False):
        base = resolve_path(root, must_exist=True)
        pattern = str(pattern or "*")
        template = str(template or "{name}")
        matches = sorted(base.glob(pattern))
        results = []
        for index, path in enumerate(matches, start=1):
            new_name = (
                template.replace("{name}", path.stem)
                .replace("{ext}", path.suffix.lstrip("."))
                .replace("{n}", str(index))
                .replace("{index}", str(index))
            )
            if not path.suffix and "." in new_name:
                pass
            elif path.suffix and not new_name.lower().endswith(path.suffix.lower()):
                new_name += path.suffix
            target = path.with_name(new_name)
            results.append(f"{path.name} -> {target.name}")
            if not dry_run and target != path:
                if target.exists():
                    results[-1] += " [пропущено: занято]"
                    continue
                journal().record_move(path, target)
                path.rename(target)
        prefix = "[DRY-RUN] " if dry_run else ""
        return prefix + "\n".join(results) if results else "Файлы не найдены."

    @registry.tool(
        "recycle_bin_list",
        "Показать содержимое корзины.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="files",
    )
    def recycle_bin_list(limit=50):
        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$bin = $shell.Namespace(10); "
            f"$bin.Items() | Select-Object -First {max(1, int(limit or 50))} "
            "Name, @{N='Path';E={$_.Path}} | ConvertTo-Json -Compress"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "recycle_bin_empty",
        "Очистить корзину.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        category="files",
        danger="dangerous",
    )
    def recycle_bin_empty():
        script = (
            "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; "
            "'Корзина очищена.'"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "file_encrypt",
        "Зашифровать файл AES-ключом из data/secret.key.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
        danger="confirm",
    )
    def file_encrypt(path):
        cryptography = optional_import("cryptography.fernet")
        if cryptography is None:
            return "Для шифрования установите cryptography."
        target = resolve_path(path, must_exist=True)
        key_path = BASE_DIR / "data" / "secret.key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = cryptography.Fernet.generate_key()
            key_path.write_bytes(key)
        token = cryptography.Fernet(key).encrypt(target.read_bytes())
        encrypted = target.with_suffix(target.suffix + ".enc")
        journal().record_write(encrypted)
        encrypted.write_bytes(token)
        return f"Зашифровано: {encrypted}"

    @registry.tool(
        "file_decrypt",
        "Расшифровать файл, созданный file_encrypt.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
        danger="confirm",
    )
    def file_decrypt(path):
        cryptography = optional_import("cryptography.fernet")
        if cryptography is None:
            return "Для расшифровки установите cryptography."
        target = resolve_path(path, must_exist=True)
        key_path = BASE_DIR / "data" / "secret.key"
        if not key_path.exists():
            return "Ключ data/secret.key не найден."
        data = cryptography.Fernet(key_path.read_bytes()).decrypt(
            target.read_bytes()
        )
        output = target.with_suffix("")
        if output == target:
            output = target.with_name(target.name + ".dec")
        journal().record_write(output)
        output.write_bytes(data)
        return f"Расшифровано: {output}"

    @registry.tool(
        "file_secure_delete",
        "Перезаписать файл случайными данными и удалить.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
        danger="dangerous",
    )
    def file_secure_delete(path):
        target = resolve_path(path, must_exist=True)
        if not target.is_file():
            return "Безопасное удаление поддерживается только для файлов."
        size = target.stat().st_size
        with target.open("r+b") as file:
            file.write(os.urandom(size))
            file.flush()
            os.fsync(file.fileno())
        target.unlink()
        return f"Файл безопасно удалён: {target}"

    @registry.tool(
        "json_read",
        "Прочитать JSON-файл.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="files",
    )
    def json_read(path):
        target = resolve_path(path, must_exist=True)
        data = json.loads(target.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)

    @registry.tool(
        "json_write",
        "Записать JSON-файл.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["path", "data"],
        },
        category="files",
        danger="confirm",
    )
    def json_write(path, data):
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(target)
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return f"JSON записан: {target}"

    @registry.tool(
        "csv_read",
        "Прочитать CSV-файл.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="files",
    )
    def csv_read(path, limit=100):
        target = resolve_path(path, must_exist=True)
        with target.open(encoding="utf-8", errors="replace", newline="") as file:
            reader = csv.reader(file)
            rows = []
            for index, row in enumerate(reader):
                if index >= max(1, int(limit or 100)):
                    break
                rows.append(row)
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @registry.tool(
        "csv_write",
        "Записать CSV-файл из массива строк.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "rows": {"type": "array"},
            },
            "required": ["path", "rows"],
        },
        category="files",
        danger="confirm",
    )
    def csv_write(path, rows):
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(target)
        with target.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            for row in rows:
                writer.writerow(row if isinstance(row, list) else [row])
        return f"CSV записан: {target}"

    @registry.tool(
        "file_permissions",
        "Показать или изменить права доступа к файлу (icacls).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "grant": {"type": "string"},
                "user": {"type": "string"},
            },
            "required": ["path"],
        },
        category="files",
        danger="confirm",
    )
    def file_permissions(path, grant=None, user=None):
        target = resolve_path(path, must_exist=True)
        if grant and user:
            result = run_command(
                ["icacls", str(target), "/grant", f"{user}:{grant}"],
                timeout=30,
            )
            return result["stdout"] or result["stderr"]
        result = run_command(["icacls", str(target)], timeout=30)
        return result["stdout"] or result["stderr"]
