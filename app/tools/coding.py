import ast
import difflib
import fnmatch
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from app.safety import contains_secret
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


DANGEROUS_COMMAND_RE = re.compile(
    r"(?i)(?:"
    r"\bformat\s+[a-z]:|"
    r"\b(?:rd|rmdir)\s+/s\b|"
    r"\bdel\s+/[fsq]\b|"
    r"\brm\s+-[a-z]*r[a-z]*f\b|"
    r"\bgit\s+reset\s+--hard\b|"
    r"\bgit\s+clean\s+-[a-z]*f|"
    r"\bgit\s+push\s+.*--force\b|"
    r"\bgit\s+push\s+-f\b|"
    r"\bshutdown\s+/s\b|"
    r"\bRemove-Item\b.*-Recurse\b"
    r")"
)


def _code_state(registry):
    return getattr(registry.context, "code_state", None)


def _is_active(state):
    return bool(state is not None and getattr(state, "active", False))


def _inside(root, target):
    try:
        Path(target).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _guard_path(registry, root, target):
    config = getattr(registry.context, "config", {}) or {}
    code = config.get("code", {}) if isinstance(config, dict) else {}
    if not isinstance(code, dict):
        code = {}
    if code.get("allow_outside_project", False):
        return None
    if _inside(root, target):
        return None
    return (
        f"Ошибка: путь вне проекта запрещён: {target}. "
        f"Корень проекта: {root}. "
        "Смените code.project или включите code.allow_outside_project."
    )


def _require_plan(registry, state):
    if not _is_active(state):
        return None
    if not getattr(state, "plan", None):
        return (
            "Ошибка: сначала вызови code_plan со списком шагов, "
            "затем продолжай правки."
        )
    return None


def _require_read(registry, state, target):
    if not _is_active(state):
        return None
    if not Path(target).exists():
        return None
    if state.has_read(target):
        return None
    return (
        f"Ошибка: сначала прочитай файл через code_read: "
        f"{target}. Слепые правки запрещены."
    )


def _newline_for(text):
    return "\r\n" if "\r\n" in text else "\n"


def _write_text(path, text, encoding="utf-8"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.jarvis-tmp")
    with temp.open(
        "w",
        encoding=encoding or "utf-8",
        errors="replace",
        newline="",
    ) as file:
        file.write(text)
    os.replace(temp, path)


def _apply_edit(text, old, new, replace_all=False):
    if old in text:
        count = text.count(old)
        if count > 1 and not replace_all:
            return None, count, False
        return (
            text.replace(old, new)
            if replace_all
            else text.replace(old, new, 1),
            count,
            False,
        )

    newline = _newline_for(text)
    normalized = text.replace("\r\n", "\n")
    old_normalized = old.replace("\r\n", "\n")
    if old_normalized not in normalized:
        return None, 0, False
    count = normalized.count(old_normalized)
    if count > 1 and not replace_all:
        return None, count, False
    updated = (
        normalized.replace(old_normalized, new.replace("\r\n", "\n"))
        if replace_all
        else normalized.replace(
            old_normalized,
            new.replace("\r\n", "\n"),
            1,
        )
    )
    if newline == "\r\n":
        updated = updated.replace("\n", "\r\n")
    return updated, count, True


def _diff_text(path, old, new, limit=6000):
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
            n=3,
        )
    )
    return truncate(diff, limit=limit) if diff else ""


def _candidate_lines(text, old):
    needle = old.strip().splitlines()
    if not needle:
        return ""
    first = needle[0].strip()
    hits = [
        index + 1
        for index, line in enumerate(text.splitlines())
        if first and first in line.strip()
    ]
    return ", ".join(str(item) for item in hits[:12])


def _read_project_rules(root):
    chunks = []
    for name in (
        "AGENTS.md",
        "CLAUDE.md",
        ".jarvis/instructions.md",
        ".cursorrules",
    ):
        path = root / name
        if not path.is_file():
            continue
        text, _ = _read_text(path, max_chars=2500)
        if text:
            chunks.append(f"[{name}]\n{text.strip()}")
    return "\n\n".join(chunks)


def _detected_commands(root):
    commands = []
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text, _ = _read_text(pyproject, max_chars=6000)
        if "pytest" in text:
            commands.append("pytest")
        if "ruff" in text:
            commands.append("ruff")
    package = root / "package.json"
    if package.exists():
        try:
            data = json.loads(
                package.read_text(encoding="utf-8", errors="replace")
            )
            scripts = data.get("scripts", {})
            if isinstance(scripts, dict):
                commands.extend(f"npm run {name}" for name in scripts)
        except (OSError, ValueError):
            pass
    for marker, command in (
        ("Cargo.toml", "cargo test"),
        ("go.mod", "go test ./..."),
        ("pom.xml", "mvn test"),
        ("build.gradle", "gradlew test"),
    ):
        if (root / marker).exists():
            commands.append(command)
    return ", ".join(dict.fromkeys(commands)) or "не определены"


def _changed_from_git(root):
    result = run_command(
        ["git", "status", "--porcelain"],
        timeout=30,
        cwd=root,
    )
    if not result.get("ok"):
        return []
    files = []
    for line in (result.get("stdout") or "").splitlines():
        text = line[3:].strip()
        if " -> " in text:
            text = text.split(" -> ", 1)[1]
        if text:
            files.append(text)
    return files


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

    state = _code_state(registry)

    def _publish_state():
        if state is None:
            return
        publish = getattr(registry.context, "publish", None)
        if publish is not None:
            try:
                publish("code_state", state.snapshot())
            except Exception:
                pass

    @registry.tool(
        "code_plan",
        "Составить план кодовой задачи. Вызывай первым перед правками.",
        {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "status": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                },
                "project": {"type": "string"},
            },
            "required": ["steps"],
        },
        category="code",
        tags=("код", "план", "plan", "todo"),
    )
    def code_plan(steps, project=None):
        if state is None:
            return "Ошибка: состояние кодовой задачи недоступно."
        if project:
            state.project = str(project)
        result = state.set_plan(steps)
        _publish_state()
        return result

    @registry.tool(
        "code_plan_update",
        "Обновить статус шага плана.",
        {
            "type": "object",
            "properties": {
                "step": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "running",
                        "done",
                        "failed",
                        "blocked",
                    ],
                },
                "note": {"type": "string"},
            },
            "required": ["step", "status"],
        },
        category="code",
        tags=("код", "план", "todo"),
    )
    def code_plan_update(step, status="done", note=""):
        if state is None:
            return "Ошибка: состояние кодовой задачи недоступно."
        result = state.update_plan_step(step, status, note)
        _publish_state()
        return result

    @registry.tool(
        "code_checkpoint",
        "Зафиксировать текущие изменения задачи для отката.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        category="code",
        tags=("код", "checkpoint", "откат", "rollback"),
    )
    def code_checkpoint():
        if state is None:
            return "Ошибка: состояние кодовой задачи недоступно."
        if not state.changed_files:
            return "Изменений пока нет."
        return (
            f"Checkpoint: файлов изменено {len(state.changed_files)}, "
            f"резервных копий {len(state.backups)}."
        )

    @registry.tool(
        "code_rollback",
        "Откатить все изменения текущей кодовой задачи.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        category="code",
        danger="dangerous",
        tags=("код", "rollback", "откат", "undo"),
    )
    def code_rollback():
        if state is None:
            return "Ошибка: состояние кодовой задачи недоступно."
        result = state.rollback()
        _publish_state()
        return result

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
                "path": {"type": "string"},
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
        path=None,
        include="*",
        case_sensitive=False,
        context=0,
        limit=100,
    ):
        root = project_path(project)
        if str(path or "").strip() not in {"", ".", "./"}:
            root = resolve_path(path, base=root, must_exist=True)
            if not root.is_dir():
                root = root.parent
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
        if state is not None:
            state.mark_read(target)
        total_lines = len(text.splitlines())
        if total_lines == 0:
            return f"Файл: {_relative(target, root)}\n(файл пуст)"
        requested = max(1, int(offset or 1))
        note = ""
        if requested > total_lines:
            requested = max(
                1,
                total_lines - max(1, int(limit or 600)) + 1,
            )
            note = (
                f"Внимание: offset={offset} больше числа строк "
                f"({total_lines}); показан конец файла.\n"
            )
        return (
            f"Файл: {_relative(target, root)} "
            f"({total_lines} строк)\n"
            + note
            + _line_numbered(text, offset=requested, limit=limit)
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
            if state is not None:
                state.mark_read(target)
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
        rules = _read_project_rules(root)
        commands = _detected_commands(root)
        context = ""
        if rules:
            context = f"\n\nПравила проекта:\n{rules}"
        return (
            f"{info}\n\n{test_line}\n"
            f"Команды: {commands}\n\n"
            f"Дерево:\n{tree}{context}{readme}"
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
        blocked = _guard_path(registry, root, target)
        if blocked:
            return blocked
        blocked = _require_plan(registry, state)
        if blocked:
            return blocked
        if contains_secret(content):
            return (
                "Ошибка: в содержимом найден секрет/токен. "
                "Используйте os.getenv(...) или переменную окружения."
            )
        existed = target.exists()
        old_text = ""
        if existed:
            blocked = _require_read(registry, state, target)
            if blocked:
                return blocked
            old_text = target.read_text(
                encoding=encoding or "utf-8",
                errors="replace",
            )
        backup = state.backup_file(target) if state is not None else None
        journal().record_write(target)
        _write_text(target, str(content), encoding=encoding or "utf-8")
        if state is not None:
            state.mark_changed(
                target,
                backup=backup.get("backup") if backup else None,
                existed=existed,
            )
            state.mark_read(target)
            _publish_state()
        diff = _diff_text(target, old_text, str(content)) if existed else ""
        result = (
            f"Записано: {_relative(target, root)} "
            f"({human_size(target.stat().st_size)})"
        )
        return result + (f"\n{diff}" if diff else "")

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
        blocked = _guard_path(registry, root, target)
        if blocked:
            return blocked
        blocked = _require_plan(registry, state)
        if blocked:
            return blocked
        blocked = _require_read(registry, state, target)
        if blocked:
            return blocked
        old = str(old_string or "")
        new = str(new_string or "")
        if not old:
            return "Ошибка: old_string пуст."
        if old == new:
            return "Ошибка: new_string совпадает со старым текстом."
        if contains_secret(new):
            return (
                "Ошибка: в new_string найден секрет/токен. "
                "Используйте os.getenv(...) или переменную окружения."
            )
        try:
            raw = target.read_bytes()
        except OSError as error:
            return f"Ошибка чтения {target}: {error}"
        if b"\x00" in raw[:4096]:
            return f"Ошибка: файл похож на бинарный: {target}"
        text = raw.decode(encoding or "utf-8", errors="replace")
        updated, count, normalized = _apply_edit(
            text,
            old,
            new,
            replace_all=bool(replace_all),
        )
        if updated is None and count == 0:
            candidates = _candidate_lines(text, old)
            hint = f" Похожие строки: {candidates}." if candidates else ""
            return (
                "Ошибка: old_string не найден в файле. "
                "Прочитай актуальный фрагмент через code_read и повтори."
                + hint
            )
        if updated is None:
            return (
                f"Ошибка: old_string встречается {count} раз. "
                "Уточните фрагмент или включите replace_all."
            )
        backup = state.backup_file(target) if state is not None else None
        journal().record_write(target)
        _write_text(target, updated, encoding=encoding or "utf-8")
        if state is not None:
            state.mark_changed(
                target,
                backup=backup.get("backup") if backup else None,
                existed=True,
            )
            state.mark_read(target)
            _publish_state()
        diff = _diff_text(target, text, updated)
        note = " (нормализованы переносы строк)" if normalized else ""
        return (
            f"Изменено: {_relative(target, root)} "
            f"(вхождений: {count if replace_all else 1}){note}"
            + (f"\n{diff}" if diff else "")
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
        blocked = _require_plan(registry, state)
        if blocked:
            return blocked
        originals = {}
        current = {}
        order = []
        for index, item in enumerate(edits, start=1):
            if not isinstance(item, dict):
                return f"Ошибка: правка {index} должна быть объектом."
            try:
                target = resolve_path(
                    item.get("path", ""),
                    base=root,
                    must_exist=True,
                )
            except Exception as error:
                return f"Ошибка правки {index}: {error}"
            blocked = _guard_path(registry, root, target)
            if blocked:
                return blocked
            blocked = _require_read(registry, state, target)
            if blocked:
                return blocked
            key = str(target)
            if key not in current:
                originals[key] = target.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                current[key] = originals[key]
                order.append(target)
            old = str(item.get("old_string") or "")
            new = str(item.get("new_string") or "")
            if not old:
                return f"Ошибка правки {index}: old_string пуст."
            if contains_secret(new):
                return (
                    f"Ошибка правки {index}: найден секрет/токен. "
                    "Используйте os.getenv(...)."
                )
            updated, count, _ = _apply_edit(
                current[key],
                old,
                new,
                replace_all=bool(item.get("replace_all", False)),
            )
            if updated is None:
                if count == 0:
                    return (
                        f"Ошибка правки {index}: old_string не найден в "
                        f"{_relative(target, root)}. Ничего не изменено."
                    )
                return (
                    f"Ошибка правки {index}: old_string встречается "
                    f"{count} раз. Ничего не изменено."
                )
            current[key] = updated
        for target in order:
            key = str(target)
            backup = state.backup_file(target) if state is not None else None
            journal().record_write(target)
            _write_text(target, current[key], encoding="utf-8")
            if state is not None:
                state.mark_changed(
                    target,
                    backup=backup.get("backup") if backup else None,
                    existed=True,
                )
                state.mark_read(target)
        if state is not None:
            _publish_state()
        results = []
        for target in order:
            key = str(target)
            diff = _diff_text(target, originals[key], current[key])
            results.append(
                f"Изменено: {_relative(target, root)}"
                + (f"\n{diff}" if diff else "")
            )
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
        blocked = _require_plan(registry, state)
        if blocked:
            return blocked
        if not check_only and re.search(
            r"(?m)^(?:---|\+\+\+)\s+(?:[A-Za-z]:|[ab]/\.\.)",
            text,
        ):
            return "Ошибка: патч затрагивает путь вне проекта."
        targets = []
        for match in re.finditer(r"(?m)^\+\+\+\s+b/(.+)$", text):
            name = match.group(1).strip()
            if name and name != "/dev/null":
                try:
                    targets.append(resolve_path(name, base=root))
                except Exception:
                    pass
        if not check_only:
            for target in targets:
                blocked = _guard_path(registry, root, target)
                if blocked:
                    return blocked
                if target.exists():
                    blocked = _require_read(registry, state, target)
                    if blocked:
                        return blocked
                    if state is not None:
                        state.backup_file(target)
                    journal().record_write(target)
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
            if not check_only and state is not None:
                for target in targets:
                    state.mark_changed(target)
                _publish_state()
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
        text = str(command or "").strip()
        if not text:
            return "Ошибка: команда пуста."
        if DANGEROUS_COMMAND_RE.search(text):
            return (
                "Ошибка: команда заблокирована как разрушительная. "
                "Используйте безопасный аналог."
            )
        config = getattr(registry.context, "config", {}) or {}
        code = config.get("code", {}) if isinstance(config, dict) else {}
        if not isinstance(code, dict):
            code = {}
        if not code.get("allow_git_write", False) and re.search(
            r"(?i)\bgit\s+(?:commit|push|tag)\b",
            text,
        ):
            return (
                "Ошибка: git commit/push/tag запрещены настройкой "
                "code.allow_git_write."
            )
        result = run_command(
            text,
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
                "path": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        danger="confirm",
        timeout=1200.0,
        tags=("код", "тесты", "pytest", "unittest"),
    )
    def code_test(project=None, timeout=900, path=""):
        root = project_path(project)
        target = str(path or "").strip()
        if target:
            target_path = resolve_path(target, base=root, must_exist=True)
            if target_path.suffix == ".py" and _module_available("pytest"):
                command = [
                    sys.executable, "-m", "pytest", "-q",
                    str(target_path),
                ]
            else:
                command = [
                    sys.executable, "-m", "compileall", "-q",
                    str(target_path),
                ]
        elif (root / "package.json").exists():
            command = ["npm", "test"]
        elif (root / "Cargo.toml").exists():
            command = ["cargo", "test"]
        elif (root / "go.mod").exists():
            command = ["go", "test", "./..."]
        elif (root / "pom.xml").exists():
            command = ["mvn", "test", "-q"]
        elif (root / "build.gradle").exists() or (
            root / "build.gradle.kts"
        ).exists():
            command = ["gradlew", "test"]
        elif _module_available("pytest") and (
            (root / "tests").is_dir()
            or any(_iter_files(root, "test_*.py", limit=1))
        ):
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
        status = "OK" if result.get("ok") else "FAIL"
        return truncate(
            f"[{status}] Команда: {' '.join(command)}\n{text}",
            limit=12000,
        )

    @registry.tool(
        "code_lint",
        "Запустить ruff, если доступен, иначе compileall.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "path": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        danger="confirm",
        timeout=600.0,
        tags=("код", "lint", "ruff", "проверка"),
    )
    def code_lint(project=None, timeout=300, path="."):
        root = project_path(project)
        target = str(path or ".").strip() or "."
        if _module_available("ruff"):
            command = [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                target,
            ]
        else:
            command = [
                sys.executable, "-m", "compileall", "-q", target,
            ]
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
        "code_verify",
        "Проверить изменённые файлы: синтаксис, lint, diff и тесты.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="code",
        tags=("код", "verify", "тесты", "проверка"),
    )
    def code_verify(project=None, timeout=900):
        root = project_path(project)
        raw_files = list(getattr(state, "changed_files", []) or [])
        if not raw_files:
            raw_files = _changed_from_git(root)
        files = []
        for item in raw_files:
            target = Path(item)
            if not target.is_absolute():
                target = (root / target).resolve()
            if target.exists() and target.is_file() and _inside(root, target):
                files.append(target)
        if not files:
            message = "Изменений нет — проверять нечего."
            if state is not None:
                state.record_check(
                    "code_verify",
                    True,
                    message,
                    mark_verified=True,
                )
                _publish_state()
            return message

        checks = []
        py_files = [item for item in files if item.suffix == ".py"]
        if py_files:
            result = run_command(
                [sys.executable, "-m", "compileall", "-q", *map(str, py_files)],
                timeout=300,
                cwd=root,
            )
            checks.append(
                (
                    "compileall",
                    bool(result.get("ok")),
                    (result.get("stdout") or "")
                    + (result.get("stderr") or ""),
                )
            )
        if py_files and _module_available("ruff"):
            result = run_command(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--no-cache",
                    *map(str, py_files),
                ],
                timeout=300,
                cwd=root,
            )
            checks.append(
                (
                    "ruff",
                    bool(result.get("ok")),
                    (result.get("stdout") or "")
                    + (result.get("stderr") or ""),
                )
            )
        git_check = run_command(
            ["git", "diff", "--check"],
            timeout=60,
            cwd=root,
        )
        if git_check.get("ok") or "not a git repository" not in (
            git_check.get("stderr") or ""
        ).lower():
            checks.append(
                (
                    "git diff --check",
                    bool(git_check.get("ok")),
                    (git_check.get("stderr") or "")
                    + (git_check.get("stdout") or ""),
                )
            )

        config = getattr(registry.context, "config", {}) or {}
        code = config.get("code", {}) if isinstance(config, dict) else {}
        if not isinstance(code, dict):
            code = {}
        if code.get("verify_tests", True):
            test_result = code_test(
                project=str(root),
                timeout=timeout,
            )
            lowered = test_result.lower()
            tests_ok = (
                "[ok]" in lowered
                and "failed" not in lowered
                and "error" not in lowered
            )
            checks.append(("tests", tests_ok, test_result))

        ok = all(item[1] for item in checks)
        lines = [f"[{'OK' if ok else 'ЕСТЬ ОШИБКИ'}] Проверка изменений"]
        for name, passed, detail in checks:
            text = re.sub(r"\s+", " ", str(detail or "")).strip()
            lines.append(
                f"- {'OK' if passed else 'FAIL'} {name}: {text[:500]}"
            )
        summary = "\n".join(lines)
        if state is not None:
            state.record_check(
                "code_verify",
                ok,
                summary,
                mark_verified=ok,
            )
            _publish_state()
        return truncate(summary, limit=12000)

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
