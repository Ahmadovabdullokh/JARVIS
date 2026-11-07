import ast
import fnmatch
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from app.tools.common import (
    BASE_DIR,
    human_size,
    resolve_path,
    run_command,
    truncate,
)
from app.undo import journal

IGNORED_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "dist_installer",
    "models",
    "node_modules",
    "venv",
}

TEXT_SUFFIXES = {
    "",
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".pyi",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def _relative(path, root):
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _iter_files(root, pattern="*", limit=2000, text_only=False):
    count = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(
            name for name in dirs if name not in IGNORED_DIRS
        )
        for name in sorted(files):
            path = Path(current) / name
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue
            if text_only and path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield path
            count += 1
            if count >= limit:
                return


def _read_text(path, max_chars=20000):
    try:
        data = path.read_bytes()
    except OSError as error:
        return None, f"Ошибка чтения {path}: {error}"
    if b"\x00" in data[:4096]:
        return None, f"Файл похож на бинарный: {path}"
    text = data.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[файл обрезан]"
    return text, ""


def _line_numbered(text, offset=1, limit=200):
    lines = text.splitlines()
    start = max(0, int(offset or 1) - 1)
    end = min(len(lines), start + max(1, int(limit or 200)))
    return "\n".join(
        f"{index + 1: 5d} | {lines[index]}"
        for index in range(start, end)
    )


def register(registry):

    def project_path(project=None):
        config = getattr(registry.context, "config", {}) or {}
        code = config.get("code", {}) if isinstance(config, dict) else {}
        if not isinstance(code, dict):
            code = {}
        default = resolve_path(
            code.get("project") or str(BASE_DIR),
            must_exist=False,
        )
        text = str(project or "").strip().strip('"').strip("'")
        if not text or text in {".", "./"}:
            return default if default.is_dir() else default.parent

        expanded = Path(
            os.path.expandvars(os.path.expanduser(text))
        )
        candidates = []
        if expanded.is_absolute():
            candidates.append(expanded)
        else:
            parts = re.split(r"[\\/]+", text)
            if parts and parts[0] == default.name:
                candidates.append(default.joinpath(*parts[1:]))
            candidates.extend(
                [
                    default.parent / expanded,
                    default / expanded,
                    Path.home() / "PycharmProjects" / expanded,
                    Path.cwd() / expanded,
                    Path.home() / expanded,
                ]
            )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists():
                return (
                    resolved if resolved.is_dir() else resolved.parent
                )
        raise FileNotFoundError(
            f"Папка проекта не найдена: {text}"
        )

    @registry.tool(
        "code_tree",
        "Показать дерево проекта без служебных папок.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "max_depth": {"type": "integer"},
                "max_entries": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "проект", "дерево", "tree"),
    )
    def code_tree(project=None, max_depth=3, max_entries=300):
        root = project_path(project)
        limit = max(20, min(int(max_entries or 300), 2000))
        depth_limit = max(1, min(int(max_depth or 3), 12))
        lines = [f"Проект: {root}"]
        entries = 0

        def walk(folder, depth, prefix):
            nonlocal entries
            if depth > depth_limit or entries >= limit:
                return
            try:
                children = sorted(
                    folder.iterdir(),
                    key=lambda item: (item.is_file(), item.name.lower()),
                )
            except OSError:
                return
            for index, item in enumerate(children):
                if entries >= limit:
                    return
                if item.is_dir() and item.name in IGNORED_DIRS:
                    continue
                branch = "└── " if index == len(children) - 1 else "├── "
                suffix = "/" if item.is_dir() else ""
                lines.append(f"{prefix}{branch}{item.name}{suffix}")
                entries += 1
                if item.is_dir():
                    child_prefix = prefix + (
                        "    " if index == len(children) - 1 else "│   "
                    )
                    walk(item, depth + 1, child_prefix)

        walk(root, 1, "")
        if entries >= limit:
            lines.append("…[дерево обрезано]")
        return "\n".join(lines)

    @registry.tool(
        "code_glob",
        "Найти файлы проекта по glob-шаблону.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "project": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["pattern"],
        },
        category="code",
        tags=("код", "файлы", "glob", "поиск"),
    )
    def code_glob(pattern, project=None, limit=200):
        root = project_path(project)
        expression = str(pattern or "*").strip()
        limit = max(1, min(int(limit or 200), 2000))
        found = []
        try:
            for path in root.glob(expression):
                if any(part in IGNORED_DIRS for part in path.parts):
                    continue
                found.append(_relative(path, root))
                if len(found) >= limit:
                    break
        except (OSError, ValueError) as error:
            return f"Ошибка glob: {error}"
        return "\n".join(found) or "Совпадений нет."

    @registry.tool(
        "code_find_file",
        "Найти файлы проекта по фрагменту имени или пути.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "project": {"type": "string"},
                "include": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="code",
        tags=("код", "файлы", "поиск", "имя"),
    )
    def code_find_file(query, project=None, include="*", limit=50):
        root = project_path(project)
        needle = str(query or "").strip().lower()
        if not needle:
            return "Укажите фрагмент имени файла."
        limit = max(1, min(int(limit or 50), 500))
        found = []
        for path in _iter_files(root, include or "*", limit=20000):
            relative = _relative(path, root)
            if needle not in relative.lower():
                continue
            try:
                size = human_size(path.stat().st_size)
            except OSError:
                size = "?"
            found.append(f"{relative}  ({size})")
            if len(found) >= limit:
                break
        return "\n".join(found) or "Совпадений нет."

    @registry.tool(
        "code_grep",
        "Найти регулярное выражение в текстовых файлах проекта.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "project": {"type": "string"},
                "include": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "context": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["pattern"],
        },
        category="code",
        tags=("код", "grep", "поиск", "regex"),
    )
    def code_grep(
        pattern,
        project=None,
        include="*",
        case_sensitive=False,
        context=0,
        limit=100,
    ):
        root = project_path(project)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(str(pattern or ""), flags)
        except re.error as error:
            return f"Ошибка regex: {error}"
        limit = max(1, min(int(limit or 100), 1000))
        context = max(0, min(int(context or 0), 5))
        results = []
        for path in _iter_files(root, include or "*", text_only=True):
            text, error = _read_text(path, max_chars=400000)
            if text is None:
                continue
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                start = max(0, index - context)
                end = min(len(lines), index + context + 1)
                chunk = [
                    f"{_relative(path, root)}:{number + 1}: {lines[number]}"
                    for number in range(start, end)
                ]
                results.append("\n".join(chunk))
                if len(results) >= limit:
                    return "\n".join(results)
        return "\n".join(results) or "Совпадений нет."

    @registry.tool(
        "code_read",
        "Прочитать файл проекта с номерами строк.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "project": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="code",
        tags=("код", "файл", "чтение", "read"),
    )
    def code_read(
        path,
        project=None,
        offset=1,
        limit=600,
        max_chars=15000,
    ):
        root = project_path(project)
        target = resolve_path(path, base=root, must_exist=True)
        text, error = _read_text(
            target,
            max_chars=max(1000, int(max_chars or 15000)),
        )
        if text is None:
            return error
        return f"Файл: {_relative(target, root)}\n" + _line_numbered(
            text,
            offset=offset,
            limit=limit,
        )

    @registry.tool(
        "code_read_many",
        "Прочитать несколько файлов за один вызов без лишних шагов.",
        {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "project": {"type": "string"},
                "max_chars_per_file": {"type": "integer"},
                "max_total_chars": {"type": "integer"},
            },
            "required": ["paths"],
        },
        category="code",
        tags=("код", "read", "batch", "файлы"),
    )
    def code_read_many(
        paths,
        project=None,
        max_chars_per_file=6000,
        max_total_chars=14000,
    ):
        root = project_path(project)
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list) or not paths:
            return "Ошибка: paths должен быть непустым списком."
        per_file = max(1000, int(max_chars_per_file or 6000))
        total_limit = max(2000, int(max_total_chars or 14000))
        parts = []
        used = 0
        for item in paths[:20]:
            try:
                target = resolve_path(item, base=root, must_exist=True)
            except Exception as error:
                parts.append(f"=== {item} ===\n{error}")
                continue
            text, error = _read_text(target, max_chars=per_file)
            if text is None:
                parts.append(f"=== {_relative(target, root)} ===\n{error}")
                continue
            block = f"=== {_relative(target, root)} ===\n{text}"
            if used + len(block) > total_limit:
                remaining = max(0, total_limit - used)
                if remaining > 200:
                    parts.append(block[:remaining] + "\n…[обрезано]")
                parts.append("…[лимит вывода исчерпан]")
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts) or "Файлы не прочитаны."

    @registry.tool(
        "code_project_snapshot",
        "Собрать карту проекта, тесты, зависимости и README за один вызов.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "max_entries": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "snapshot", "обзор", "проект"),
    )
    def code_project_snapshot(project=None, max_entries=120):
        root = project_path(project)
        info = code_project_info(project=str(root))
        tree = code_tree(
            project=str(root),
            max_depth=2,
            max_entries=max_entries,
        )
        tests = [
            _relative(path, root)
            for path in _iter_files(root, "test_*.py", limit=50)
        ]
        readme = ""
        for name in ("README.md", "README.txt", "PROJECT_STATUS.md"):
            candidate = root / name
            if candidate.exists():
                text, _ = _read_text(candidate, max_chars=2000)
                if text:
                    readme = f"\n\n[{name}]\n{text.strip()}"
                    break
        test_line = (
            "Тесты: " + ", ".join(tests)
            if tests
            else "Тестовые файлы test_*.py не найдены."
        )
        return (
            f"{info}\n\n{test_line}\n\n"
            f"Дерево:\n{tree}{readme}"
        )

    @registry.tool(
        "code_write",
        "Создать или перезаписать файл проекта с записью в undo.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "project": {"type": "string"},
                "encoding": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        category="code",
        danger="confirm",
        tags=("код", "файл", "запись", "write"),
    )
    def code_write(path, content, project=None, encoding="utf-8"):
        root = project_path(project)
        target = resolve_path(path, base=root)
        target.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(target)
        target.write_text(
            str(content),
            encoding=encoding or "utf-8",
        )
        return (
            f"Записано: {_relative(target, root)} "
            f"({human_size(target.stat().st_size)})"
        )

    @registry.tool(
        "code_edit",
        "Точечно заменить строку в файле, как edit в opencode.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "project": {"type": "string"},
                "replace_all": {"type": "boolean"},
                "encoding": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        category="code",
        danger="confirm",
        tags=("код", "edit", "замена", "правка"),
    )
    def code_edit(
        path,
        old_string,
        new_string,
        project=None,
        replace_all=False,
        encoding="utf-8",
    ):
        root = project_path(project)
        target = resolve_path(path, base=root, must_exist=True)
        old = str(old_string or "")
        new = str(new_string or "")
        if not old:
            return "Ошибка: old_string пуст."
        text = target.read_text(
            encoding=encoding or "utf-8",
            errors="replace",
        )
        count = text.count(old)
        if count == 0:
            return "Ошибка: old_string не найден в файле."
        if count > 1 and not replace_all:
            return (
                f"Ошибка: old_string встречается {count} раз. "
                "Уточните фрагмент или включите replace_all."
            )
        updated = (
            text.replace(old, new)
            if replace_all
            else text.replace(old, new, 1)
        )
        journal().record_write(target)
        target.write_text(
            updated,
            encoding=encoding or "utf-8",
        )
        line = updated[: updated.find(new)].count("\n") + 1 if new else 1
        return (
            f"Изменено: {_relative(target, root)} "
            f"(вхождений: {count if replace_all else 1}, строка ~{line})"
        )

    @registry.tool(
        "code_multi_edit",
        "Применить несколько точечных правок к файлам проекта.",
        {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                    },
                },
                "project": {"type": "string"},
            },
            "required": ["edits"],
        },
        category="code",
        danger="confirm",
        tags=("код", "edit", "multi", "правки"),
    )
    def code_multi_edit(edits, project=None):
        root = project_path(project)
        if not isinstance(edits, list) or not edits:
            return "Ошибка: edits должен быть непустым списком."
        results = []
        for item in edits:
            if not isinstance(item, dict):
                results.append("Пропуск: некорректный edit.")
                continue
            result = code_edit(
                item.get("path", ""),
                item.get("old_string", ""),
                item.get("new_string", ""),
                project=str(root),
                replace_all=bool(item.get("replace_all", False)),
            )
            results.append(str(result))
            if str(result).startswith("Ошибка"):
                break
        return "\n".join(results)

    @registry.tool(
        "code_apply_patch",
        "Применить unified diff через git apply в проекте.",
        {
            "type": "object",
            "properties": {
                "patch": {"type": "string"},
                "project": {"type": "string"},
                "check_only": {"type": "boolean"},
            },
            "required": ["patch"],
        },
        category="code",
        danger="confirm",
        timeout=300.0,
        tags=("код", "patch", "diff", "git"),
    )
    def code_apply_patch(patch, project=None, check_only=False):
        root = project_path(project)
        text = str(patch or "").strip()
        if not text:
            return "Ошибка: патч пуст."
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".patch",
            delete=False,
            encoding="utf-8",
        )
        try:
            handle.write(text)
            handle.close()
            command = ["git", "apply", "--whitespace=nowarn"]
            if check_only:
                command.append("--check")
            command.append(handle.name)
            result = run_command(command, timeout=300, cwd=root)
        finally:
            try:
                Path(handle.name).unlink(missing_ok=True)
            except OSError:
                pass
        if result.get("ok"):
            return "Патч применён." if not check_only else "Патч корректен."
        detail = (result.get("stderr") or result.get("stdout") or "").strip()
        return f"Ошибка git apply:\n{detail[:4000]}"

    @registry.tool(
        "code_diff",
        "Показать git diff проекта или отдельного файла.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "project": {"type": "string"},
                "staged": {"type": "boolean"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "diff", "git"),
    )
    def code_diff(path=None, project=None, staged=False):
        root = project_path(project)
        command = ["git", "diff"]
        if staged:
            command.append("--staged")
        if path:
            command.extend(["--", str(path)])
        result = run_command(command, timeout=120, cwd=root)
        if not result.get("ok"):
            return (
                "Ошибка git diff: "
                + (result.get("stderr") or "").strip()[:2000]
            )
        return truncate(
            (result.get("stdout") or "").strip() or "Изменений нет.",
            limit=12000,
        )

    @registry.tool(
        "code_git_summary",
        "Кратко показать branch, status и последние коммиты.",
        {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": [],
        },
        category="code",
        tags=("код", "git", "status", "log"),
    )
    def code_git_summary(project=None):
        root = project_path(project)
        commands = (
            ("branch", ["git", "branch", "--show-current"]),
            ("status", ["git", "status", "--short"]),
            ("log", ["git", "log", "--oneline", "-5"]),
        )
        lines = []
        for label, command in commands:
            result = run_command(command, timeout=60, cwd=root)
            output = (
                (result.get("stdout") or "").strip()
                or (result.get("stderr") or "").strip()
                or "нет данных"
            )
            lines.append(f"[{label}]\n{output}")
        return "\n\n".join(lines)

    @registry.tool(
        "code_run",
        "Выполнить команду в папке проекта и вернуть вывод.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "project": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        category="code",
        danger="confirm",
        timeout=900.0,
        tags=("код", "run", "shell", "terminal"),
    )
    def code_run(command, project=None, timeout=300):
        root = project_path(project)
        result = run_command(
            str(command or ""),
            timeout=max(10, min(int(timeout or 300), 1800)),
            cwd=root,
            shell=True,
        )
        output = []
        if result.get("stdout"):
            output.append(result["stdout"].strip())
        if result.get("stderr"):
            output.append("[stderr] " + result["stderr"].strip())
        output.append(
            f"[exit {result.get('returncode')}, "
            f"{result.get('elapsed')} c]"
        )
        return truncate("\n".join(output), limit=12000)

    @registry.tool(
        "code_test",
        "Определить и запустить тесты проекта.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        danger="confirm",
        timeout=1200.0,
        tags=("код", "тесты", "pytest", "unittest"),
    )
    def code_test(project=None, timeout=900):
        root = project_path(project)
        if (root / "tests").is_dir() and _module_available("pytest"):
            command = [sys.executable, "-m", "pytest", "-q"]
        elif (root / "tests").is_dir():
            command = [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-q",
            ]
        else:
            command = [sys.executable, "-m", "compileall", "-q", "."]
        result = run_command(
            command,
            timeout=max(30, min(int(timeout or 900), 1800)),
            cwd=root,
        )
        output = (result.get("stdout") or "").strip()
        error = (result.get("stderr") or "").strip()
        text = "\n".join(
            part for part in (output, error) if part
        ) or f"Код завершения: {result.get('returncode')}"
        return truncate(
            f"Команда: {' '.join(command)}\n{text}",
            limit=12000,
        )

    @registry.tool(
        "code_lint",
        "Запустить ruff, если доступен, иначе compileall.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        danger="confirm",
        timeout=600.0,
        tags=("код", "lint", "ruff", "проверка"),
    )
    def code_lint(project=None, timeout=300):
        root = project_path(project)
        if _module_available("ruff"):
            command = [sys.executable, "-m", "ruff", "check", "."]
        else:
            command = [sys.executable, "-m", "compileall", "-q", "."]
        result = run_command(
            command,
            timeout=max(20, min(int(timeout or 300), 1200)),
            cwd=root,
        )
        output = "\n".join(
            part
            for part in (
                (result.get("stdout") or "").strip(),
                (result.get("stderr") or "").strip(),
            )
            if part
        )
        status = "OK" if result.get("ok") else "ЕСТЬ ОШИБКИ"
        return truncate(
            f"[{status}] {' '.join(command)}\n{output}",
            limit=12000,
        )

    @registry.tool(
        "code_format",
        "Отформатировать проект через ruff format или black.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": [],
        },
        category="code",
        danger="confirm",
        timeout=600.0,
        tags=("код", "format", "ruff", "black"),
    )
    def code_format(project=None, path="."):
        root = project_path(project)
        target = str(path or ".")
        if _module_available("ruff"):
            command = [sys.executable, "-m", "ruff", "format", target]
        elif _module_available("black"):
            command = [sys.executable, "-m", "black", target]
        else:
            return "Ошибка: не найден ruff или black."
        result = run_command(command, timeout=600, cwd=root)
        output = "\n".join(
            part
            for part in (
                (result.get("stdout") or "").strip(),
                (result.get("stderr") or "").strip(),
            )
            if part
        )
        return truncate(
            f"{'OK' if result.get('ok') else 'ОШИБКА'} "
            f"{' '.join(command)}\n{output}",
            limit=8000,
        )

    @registry.tool(
        "code_project_info",
        "Определить язык, размер, git-состояние и команду тестов.",
        {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": [],
        },
        category="code",
        tags=("код", "проект", "информация", "info"),
    )
    def code_project_info(project=None):
        root = project_path(project)
        counts = {}
        total = 0
        size = 0
        for path in _iter_files(root, "*", limit=20000):
            total += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
            suffix = path.suffix.lower() or "(no ext)"
            counts[suffix] = counts.get(suffix, 0) + 1
        top = sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:8]
        markers = [
            name
            for name in (
                "pyproject.toml",
                "requirements.txt",
                "package.json",
                "Cargo.toml",
                "go.mod",
                ".git",
            )
            if (root / name).exists()
        ]
        git = run_command(
            ["git", "status", "--short"],
            timeout=30,
            cwd=root,
        )
        git_status = (
            (git.get("stdout") or "").strip()
            if git.get("ok")
            else "не git-репозиторий"
        )
        return (
            f"Проект: {root}\n"
            f"Файлов: {total}, размер: {human_size(size)}\n"
            f"Типы: "
            + ", ".join(f"{key}={value}" for key, value in top)
            + f"\nМаркеры: {', '.join(markers) or 'нет'}\n"
            f"Git status:\n{git_status or 'чисто'}"
        )

    @registry.tool(
        "code_symbols",
        "Показать классы и функции Python-файла или проекта.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "project": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "python", "ast", "symbols"),
    )
    def code_symbols(path=None, project=None, limit=200):
        root = project_path(project)
        target = (
            resolve_path(path, base=root, must_exist=True)
            if path
            else root
        )
        files = (
            [target]
            if target.is_file()
            else list(_iter_files(root, "*.py", limit=100))
        )
        limit = max(1, min(int(limit or 200), 2000))
        lines = []
        for file_path in files:
            try:
                tree = ast.parse(
                    file_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
            except (OSError, SyntaxError) as error:
                lines.append(f"{_relative(file_path, root)}: {error}")
                continue
            entries = []
            for node in ast.walk(tree):
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                ):
                    kind = (
                        "class"
                        if isinstance(node, ast.ClassDef)
                        else "def"
                    )
                    entries.append(
                        f"  {node.lineno:5d} {kind} {node.name}"
                    )
            if entries:
                lines.append(f"{_relative(file_path, root)}:")
                lines.extend(entries[:limit])
            if len(lines) >= limit:
                break
        return "\n".join(lines) or "Символы не найдены."

    @registry.tool(
        "code_find_references",
        "Найти упоминания символа по файлам проекта.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "project": {"type": "string"},
                "include": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["symbol"],
        },
        category="code",
        tags=("код", "references", "symbol", "поиск"),
    )
    def code_find_references(
        symbol,
        project=None,
        include="*.py",
        limit=200,
    ):
        name = str(symbol or "").strip()
        if not name:
            return "Ошибка: symbol пуст."
        return code_grep(
            rf"\b{re.escape(name)}\b",
            project=project,
            include=include,
            case_sensitive=True,
            context=0,
            limit=limit,
        )

    @registry.tool(
        "code_todos",
        "Найти TODO, FIXME, HACK и NOTE в проекте.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "todo", "fixme", "заметки"),
    )
    def code_todos(project=None, limit=200):
        return code_grep(
            r"\b(TODO|FIXME|HACK|NOTE|XXX)\b",
            project=project,
            include="*",
            case_sensitive=True,
            context=0,
            limit=limit,
        )

    @registry.tool(
        "code_dependencies",
        "Показать зависимости проекта из типовых файлов.",
        {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": [],
        },
        category="code",
        tags=("код", "зависимости", "requirements", "deps"),
    )
    def code_dependencies(project=None):
        root = project_path(project)
        names = [
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-optional.txt",
            "pyproject.toml",
            "package.json",
        ]
        parts = []
        for name in names:
            path = root / name
            if not path.exists():
                continue
            text, error = _read_text(path, max_chars=12000)
            if text is None:
                parts.append(error)
                continue
            if name == "package.json":
                try:
                    data = json.loads(text)
                    deps = data.get("dependencies", {})
                    dev = data.get("devDependencies", {})
                    text = json.dumps(
                        {"dependencies": deps, "devDependencies": dev},
                        ensure_ascii=False,
                        indent=2,
                    )
                except ValueError:
                    pass
            parts.append(f"[{name}]\n{text.strip()}")
        return "\n\n".join(parts) or "Файлы зависимостей не найдены."


def _module_available(name):
    try:
        return __import__(name) is not None
    except Exception:
        return False
