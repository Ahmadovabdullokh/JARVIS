import os
import subprocess
import sys
import time

import requests

from app.tools.common import (
    is_admin,
    powershell,
    resolve_path,
    run_command,
)


def _decode(data):
    if isinstance(data, bytes):
        for encoding in ("utf-8", "cp866", "cp1251"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", "replace")
    return str(data)


def register(registry):

    @registry.tool(
        "run_powershell",
        "Выполнить произвольную команду PowerShell.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_powershell(command, cwd=None, timeout=120):
        return powershell(str(command), cwd=cwd, timeout=timeout)

    @registry.tool(
        "run_cmd",
        "Выполнить произвольную команду cmd.exe.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_cmd(command, cwd=None, timeout=120):
        result = run_command(
            ["cmd.exe", "/c", str(command)],
            cwd=cwd,
            timeout=timeout,
        )
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "run_python",
        "Выполнить произвольный Python-код.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["code"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_python(code, timeout=120):
        result = subprocess.run(
            [sys.executable, "-c", str(code)],
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout or 120)),
        )
        return (
            (result.stdout or "") + (result.stderr or "")
        ).strip() or f"Код возврата: {result.returncode}"

    @registry.tool(
        "run_executable",
        "Запустить любую программу с аргументами.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "args": {"type": "array"},
                "cwd": {"type": "string"},
                "wait": {"type": "boolean"},
                "timeout": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_executable(path, args=None, cwd=None, wait=True, timeout=120):
        target = resolve_path(path, must_exist=True)
        command = [str(target)] + [str(item) for item in (args or [])]
        if not wait:
            process = subprocess.Popen(command, cwd=cwd)
            return f"Запущен PID {process.pid}: {target}"
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=max(1, int(timeout or 120)),
        )
        output = _decode(result.stdout) + _decode(result.stderr)
        return output.strip() or f"Код возврата: {result.returncode}"

    @registry.tool(
        "run_script",
        "Запустить файл скрипта (.ps1, .bat, .cmd, .py).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "args": {"type": "array"},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_script(path, args=None, cwd=None, timeout=300):
        target = resolve_path(path, must_exist=True)
        suffix = target.suffix.lower()
        extra = [str(item) for item in (args or [])]
        if suffix == ".py":
            command = [sys.executable, str(target)] + extra
        elif suffix == ".ps1":
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(target),
            ] + extra
        elif suffix in (".bat", ".cmd"):
            command = ["cmd.exe", "/c", str(target)] + extra
        else:
            command = [str(target)] + extra
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=max(1, int(timeout or 300)),
        )
        output = _decode(result.stdout) + _decode(result.stderr)
        return output.strip() or f"Код возврата: {result.returncode}"

    @registry.tool(
        "run_elevated",
        "Запустить команду с правами администратора.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "wait": {"type": "boolean"},
            },
            "required": ["command"],
        },
        category="generic",
        danger="dangerous",
    )
    def run_elevated(command, wait=False):
        import ctypes

        parameters = f'/c {command}' + (" & pause" if wait else "")
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "cmd.exe",
            parameters,
            None,
            1,
        )
        if result <= 32:
            return f"Не удалось запустить с правами администратора (код {result})."
        return "Команда запущена с правами администратора."

    @registry.tool(
        "http_request",
        "Выполнить произвольный HTTP-запрос.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string"},
                "headers": {"type": "object"},
                "params": {"type": "object"},
                "json_body": {"type": "object"},
                "data": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["url"],
        },
        category="generic",
        danger="confirm",
    )
    def http_request(
        url,
        method="GET",
        headers=None,
        params=None,
        json_body=None,
        data=None,
        timeout=30,
    ):
        try:
            response = requests.request(
                str(method or "GET").upper(),
                str(url),
                headers=headers,
                params=params,
                json=json_body,
                data=data,
                timeout=float(timeout or 30),
            )
        except Exception as error:
            return f"HTTP-ошибка: {error}"
        body = response.text
        if len(body) > 12000:
            body = body[:12000] + "... (обрезано)"
        return (
            f"Статус: {response.status_code}\n"
            f"Длина: {len(response.content)} байт\n\n{body}"
        )

    @registry.tool(
        "open_url",
        "Открыть URL в браузере по умолчанию.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        category="generic",
    )
    def open_url(url):
        import webbrowser

        webbrowser.open(str(url), new=2)
        return f"Открыто: {url}"

    @registry.tool(
        "notify",
        "Показать уведомление Windows.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
        category="generic",
    )
    def notify(message, title="JARVIS"):
        from app.tools.common import notify as show

        show(str(title), str(message))
        return "Уведомление показано."

    @registry.tool(
        "sleep",
        "Подождать указанное время.",
        {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
        category="generic",
    )
    def sleep(seconds=1):
        delay = max(0, float(seconds or 1))
        time.sleep(delay)
        return f"Ожидание {delay} c завершено."

    @registry.tool(
        "whoami",
        "Текущий пользователь, домен и права.",
        {"type": "object", "properties": {}, "required": []},
        category="generic",
    )
    def whoami():
        return (
            f"Пользователь: {os.environ.get('USERNAME')}\n"
            f"Домен: {os.environ.get('USERDOMAIN')}\n"
            f"Компьютер: {os.environ.get('COMPUTERNAME')}\n"
            f"Администратор: {'да' if is_admin() else 'нет'}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"Папка: {os.getcwd()}"
        )

    @registry.tool(
        "batch_run",
        "Выполнить несколько инструментов пакетно.",
        {
            "type": "object",
            "properties": {
                "calls": {"type": "array"},
                "stop_on_error": {"type": "boolean"},
            },
            "required": ["calls"],
        },
        category="generic",
        danger="confirm",
    )
    def batch_run(calls, stop_on_error=False):
        lines = []
        for index, call in enumerate(calls or [], start=1):
            if not isinstance(call, dict):
                lines.append(f"{index}. пропуск")
                continue
            name = call.get("tool") or call.get("name")
            arguments = call.get("arguments") or {}
            if not name:
                lines.append(f"{index}. нет имени инструмента")
                continue
            result = registry.execute(str(name), arguments)
            lines.append(f"{index}. {name}: {result[:1000]}")
            if stop_on_error and (
                "Ошибка" in result or "Таймаут" in result
            ):
                break
        return "\n".join(lines)
