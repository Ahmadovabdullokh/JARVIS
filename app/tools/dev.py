import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid

from app.tools.common import (
    powershell,
    resolve_path,
    run_command,
)


def _run(command, cwd=None, timeout=120):
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout or 120)),
    )
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip() or f"Код возврата: {result.returncode}"


def register(registry):

    @registry.tool(
        "dev_run_python",
        "Выполнить Python-код или файл.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "path": {"type": "string"},
                "args": {"type": "array"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        category="dev",
        danger="dangerous",
    )
    def dev_run_python(code=None, path=None, args=None, cwd=None, timeout=120):
        command = [sys.executable]
        if path:
            command.append(str(resolve_path(path, must_exist=True)))
        elif code:
            command.extend(["-c", str(code)])
        else:
            return "Укажите code или path."
        command.extend(str(item) for item in (args or []))
        return _run(command, cwd, timeout)

    @registry.tool(
        "dev_run_powershell",
        "Выполнить PowerShell-скрипт.",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["script"],
        },
        category="dev",
        danger="dangerous",
    )
    def dev_run_powershell(script, cwd=None, timeout=120):
        return powershell(str(script), cwd=cwd, timeout=timeout)

    @registry.tool(
        "dev_run_cmd",
        "Выполнить команду cmd.exe.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        category="dev",
        danger="dangerous",
    )
    def dev_run_cmd(command, cwd=None, timeout=120):
        result = run_command(
            ["cmd.exe", "/c", str(command)],
            cwd=cwd,
            timeout=timeout,
        )
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "dev_git",
        "Операции Git в указанной папке.",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "diff",
                        "log",
                        "branch",
                        "add",
                        "commit",
                        "push",
                        "pull",
                        "checkout",
                        "clone",
                        "stash",
                        "remote",
                    ],
                },
                "args": {"type": "array"},
            },
            "required": ["repo", "action"],
        },
        category="dev",
        danger="confirm",
    )
    def dev_git(repo, action, args=None):
        base = ["git"]
        if action == "clone":
            return _run(["git", "clone"] + [str(item) for item in (args or [])], timeout=600)
        folder = str(resolve_path(repo, must_exist=True))
        mapping = {
            "status": ["status"],
            "diff": ["diff"],
            "log": ["log", "--oneline", "-20"],
            "branch": ["branch", "-a"],
            "add": ["add"] + [str(item) for item in (args or ["."])],
            "commit": ["commit", "-m"] + [str(item) for item in (args or ["update"])],
            "push": ["push"] + [str(item) for item in (args or [])],
            "pull": ["pull"] + [str(item) for item in (args or [])],
            "checkout": ["checkout"] + [str(item) for item in (args or [])],
            "stash": ["stash"] + [str(item) for item in (args or [])],
            "remote": ["remote", "-v"],
        }
        return _run(base + mapping[action], cwd=folder, timeout=600)

    @registry.tool(
        "dev_pip",
        "Управление пакетами Python.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["install", "uninstall", "list", "show", "freeze"],
                },
                "package": {"type": "string"},
            },
            "required": ["action"],
        },
        category="dev",
        danger="confirm",
    )
    def dev_pip(action, package=None):
        command = [sys.executable, "-m", "pip"]
        if action == "list":
            command.append("list")
        elif action == "freeze":
            command.append("freeze")
        elif action == "show":
            command.extend(["show", str(package)])
        elif action == "install":
            command.extend(["install", str(package)])
        elif action == "uninstall":
            command.extend(["uninstall", "-y", str(package)])
        else:
            return "Неизвестное действие."
        return _run(command, timeout=600)

    @registry.tool(
        "dev_npm",
        "Команды npm в проекте.",
        {
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["install", "run", "test", "build", "start", "list"],
                },
                "script": {"type": "string"},
            },
            "required": ["cwd", "action"],
        },
        category="dev",
        danger="confirm",
    )
    def dev_npm(cwd, action, script=None):
        folder = str(resolve_path(cwd, must_exist=True))
        mapping = {
            "install": ["npm", "install"],
            "run": ["npm", "run", str(script or "")],
            "test": ["npm", "test"],
            "build": ["npm", "run", "build"],
            "start": ["npm", "start"],
            "list": ["npm", "list", "--depth=0"],
        }
        return _run(mapping[action], cwd=folder, timeout=900)

    @registry.tool(
        "dev_tests",
        "Запустить тесты проекта.",
        {
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["pytest", "unittest"],
                },
                "args": {"type": "array"},
            },
            "required": ["cwd"],
        },
        category="dev",
    )
    def dev_tests(cwd, framework="pytest", args=None):
        folder = str(resolve_path(cwd, must_exist=True))
        if framework == "unittest":
            command = [sys.executable, "-m", "unittest"] + [
                str(item) for item in (args or ["discover", "-s", "tests", "-v"])
            ]
        else:
            command = [sys.executable, "-m", "pytest"] + [
                str(item) for item in (args or [])
            ]
        return _run(command, cwd=folder, timeout=1800)

    @registry.tool(
        "dev_lint",
        "Проверить код линтером.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "tool": {
                    "type": "string",
                    "enum": ["ruff", "flake8", "pylint", "mypy"],
                },
            },
            "required": ["path"],
        },
        category="dev",
    )
    def dev_lint(path, tool="ruff"):
        target = str(resolve_path(path, must_exist=True))
        if tool == "ruff":
            command = [sys.executable, "-m", "ruff", "check", target]
        elif tool == "flake8":
            command = [sys.executable, "-m", "flake8", target]
        elif tool == "pylint":
            command = [sys.executable, "-m", "pylint", target]
        else:
            command = [sys.executable, "-m", "mypy", target]
        return _run(command, timeout=600)

    @registry.tool(
        "dev_sqlite",
        "Выполнить SQL-запрос к SQLite.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["path", "query"],
        },
        category="dev",
        danger="confirm",
    )
    def dev_sqlite(path, query):
        database = resolve_path(path)
        connection = sqlite3.connect(str(database))
        try:
            cursor = connection.execute(str(query))
            if cursor.description:
                columns = [item[0] for item in cursor.description]
                rows = cursor.fetchmany(200)
                lines = [" | ".join(columns)]
                lines.extend(
                    " | ".join("" if value is None else str(value) for value in row)
                    for row in rows
                )
                return "\n".join(lines)
            connection.commit()
            return f"Затронуто строк: {cursor.rowcount}"
        except Exception as error:
            return f"SQL-ошибка: {error}"
        finally:
            connection.close()

    @registry.tool(
        "dev_json_format",
        "Отформатировать или проверить JSON.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "path": {"type": "string"},
                "indent": {"type": "integer"},
            },
            "required": [],
        },
        category="dev",
    )
    def dev_json_format(text=None, path=None, indent=2):
        if path:
            text = resolve_path(path, must_exist=True).read_text(encoding="utf-8")
        if not text:
            return "Укажите text или path."
        try:
            data = json.loads(str(text))
        except json.JSONDecodeError as error:
            return f"Некорректный JSON: {error}"
        return json.dumps(data, ensure_ascii=False, indent=int(indent or 2))

    @registry.tool(
        "dev_regex",
        "Проверить регулярное выражение на тексте.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "text": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["pattern", "text"],
        },
        category="dev",
    )
    def dev_regex(pattern, text, limit=50):
        try:
            matches = re.findall(str(pattern), str(text))
        except re.error as error:
            return f"Ошибка регулярного выражения: {error}"
        if not matches:
            return "Совпадений не найдено."
        return "\n".join(str(item) for item in matches[: int(limit or 50)])

    @registry.tool(
        "dev_base64",
        "Кодировать или декодировать Base64.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["encode", "decode"],
                },
            },
            "required": ["text"],
        },
        category="dev",
    )
    def dev_base64(text, action="encode"):
        try:
            if action == "decode":
                return base64.b64decode(str(text)).decode("utf-8", "replace")
            return base64.b64encode(str(text).encode("utf-8")).decode("ascii")
        except Exception as error:
            return f"Base64-ошибка: {error}"

    @registry.tool(
        "dev_hash",
        "Вычислить хеш текста.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "algorithm": {
                    "type": "string",
                    "enum": ["md5", "sha1", "sha256", "sha512"],
                },
            },
            "required": ["text"],
        },
        category="dev",
    )
    def dev_hash(text, algorithm="sha256"):
        digest = hashlib.new(str(algorithm or "sha256"))
        digest.update(str(text).encode("utf-8"))
        return digest.hexdigest()

    @registry.tool(
        "dev_uuid",
        "Сгенерировать UUID.",
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": [],
        },
        category="dev",
    )
    def dev_uuid(count=1):
        return "\n".join(
            str(uuid.uuid4()) for _ in range(max(1, min(int(count or 1), 100)))
        )

    @registry.tool(
        "dev_jwt_decode",
        "Декодировать JWT без проверки подписи.",
        {
            "type": "object",
            "properties": {"token": {"type": "string"}},
            "required": ["token"],
        },
        category="dev",
    )
    def dev_jwt_decode(token):
        parts = str(token).split(".")
        if len(parts) < 2:
            return "Некорректный JWT."
        output = []
        for part in parts[:2]:
            padded = part + "=" * (-len(part) % 4)
            try:
                output.append(
                    json.dumps(
                        json.loads(base64.urlsafe_b64decode(padded)),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            except Exception as error:
                output.append(f"Ошибка: {error}")
        return "\n".join(output)

    @registry.tool(
        "dev_docker",
        "Управление Docker.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ps",
                        "images",
                        "start",
                        "stop",
                        "rm",
                        "logs",
                        "run",
                    ],
                },
                "target": {"type": "string"},
                "args": {"type": "array"},
            },
            "required": ["action"],
        },
        category="dev",
        danger="confirm",
    )
    def dev_docker(action, target=None, args=None):
        mapping = {
            "ps": ["docker", "ps"],
            "images": ["docker", "images"],
            "start": ["docker", "start", str(target or "")],
            "stop": ["docker", "stop", str(target or "")],
            "rm": ["docker", "rm", str(target or "")],
            "logs": ["docker", "logs", "--tail", "100", str(target or "")],
            "run": ["docker", "run"] + [str(item) for item in (args or [])],
        }
        return _run(mapping[action], timeout=600)

    @registry.tool(
        "dev_venv",
        "Создать виртуальное окружение Python.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="dev",
    )
    def dev_venv(path):
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return _run(
            [sys.executable, "-m", "venv", str(target)],
            timeout=600,
        )

    @registry.tool(
        "dev_python_info",
        "Информация о Python и пакетах.",
        {"type": "object", "properties": {}, "required": []},
        category="dev",
    )
    def dev_python_info():
        return (
            f"Python: {sys.version}\n"
            f"Исполняемый файл: {sys.executable}\n"
            f"Платформа: {sys.platform}\n"
            f"Папка: {os.getcwd()}"
        )

    @registry.tool(
        "copilot_cli_status",
        "Проверить наличие GitHub Copilot CLI и статус авторизации.",
        {"type": "object", "properties": {}, "required": []},
        category="dev",
    )
    def copilot_cli_status():
        import shutil

        executable = shutil.which("copilot") or shutil.which("copilot.exe")
        if not executable:
            return (
                "Copilot CLI не установлен. "
                "Выполните 'copilot' в терминале один раз для установки "
                "и входа, или установите: "
                "winget install GitHub.Copilot_CLI."
            )
        try:
            completed = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
            )
        except Exception as error:
            return f"Copilot CLI найден ({executable}), но не отвечает: {error}"
        output = (
            (completed.stdout or "") + (completed.stderr or "")
        ).strip()
        if completed.returncode != 0:
            return (
                f"{executable}\nНе установлен (код {completed.returncode}). "
                f"{output[:300]}\n"
                "Выполните 'copilot' в терминале один раз, чтобы "
                "установить и войти, либо: "
                "winget install GitHub.Copilot_CLI."
            )
        return f"{executable}\n{output[:300]}"

    @registry.tool(
        "copilot_cli_task",
        "Дать задание агенту GitHub Copilot CLI: сам читает код, "
        "правит файлы и запускает проверку в указанном проекте.",
        {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "project": {"type": "string"},
                "timeout": {"type": "integer"},
                "cli_args": {"type": "array"},
            },
            "required": ["task"],
        },
        category="dev",
        danger="confirm",
        timeout=1200.0,
    )
    def copilot_cli_task(task, project=None, timeout=900, cli_args=None):
        import shutil

        text = str(task or "").strip()
        if not text:
            return "Ошибка: пустое задание для Copilot."

        executable = shutil.which("copilot") or shutil.which("copilot.exe")
        if not executable:
            return (
                "Ошибка: копилот CLI не установлен. "
                "Выполните 'copilot' в терминале один раз для "
                "установки и входа, или установите: "
                "winget install GitHub.Copilot_CLI. "
                "Либо переключите режим кода на резервный ассистент."
            )

        cwd = None
        if str(project or "").strip():
            cwd = resolve_path(project, must_exist=False)
            if not cwd.exists():
                return f"Ошибка: папка проекта {cwd} не найдена."

        command = [executable, "-p", text]
        command.extend(str(item) for item in (cli_args or []))

        print(f"[COPILOT] Запуск CLI в {cwd or os.getcwd()} ({timeout} c)…")
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=max(60, int(timeout or 900)),
            )
        except subprocess.TimeoutExpired:
            return (
                "Ошибка: Copilot CLI не завершил задание "
                f"за {timeout} c. Возможно, требуется больше времени."
            )
        except FileNotFoundError:
            return "Ошибка: Copilot CLI найден, но не запустился."

        output = (
            (completed.stdout or "") + (completed.stderr or "")
        ).strip()

        if completed.returncode != 0:
            lowered = output.lower()
            if "was not found" in lowered or "not found" in lowered:
                return (
                    "Ошибка: Copilot CLI не установлен (шим VS Code). "
                    "Выполните 'copilot' в терминале один раз для "
                    "установки и входа, либо: "
                    "winget install GitHub.Copilot_CLI."
                )
            return (
                f"Ошибка: Copilot CLI завершился с кодом "
                f"{completed.returncode}.\n{output[:2000]}"
            )

        if len(output) > 8000:
            output = (
                output[:8000]
                + "\n…[вывод Copilot обрезан]"
            )
        return output or "Copilot завершил без вывода."

    @registry.tool(
        "copilot_vscode_task",
        "Передать задание в GitHub Copilot Chat в VS Code "
        "через окно и клавиатуру, затем проверить результат OCR.",
        {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["task"],
        },
        category="dev",
        danger="confirm",
    )
    def copilot_vscode_task(task, project=None):
        if not str(task or "").strip():
            return "Ошибка: пустое задание для Copilot."
        if str(project or "").strip():
            arguments = {
                "project": str(project),
                "prompt": str(task),
            }
        else:
            arguments = {"prompt": str(task)}
        return registry.execute("automation_copilot_fix", arguments)
