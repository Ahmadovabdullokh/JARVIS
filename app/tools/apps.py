import os
import shutil
import subprocess
import time
from pathlib import Path

from app.tools.common import (
    activate_window,
    powershell,
    ps_quote,
    resolve_path,
    run_command,
)

ALIASES = {
    "блокнот": "notepad.exe",
    "notepad": "notepad.exe",
    "калькулятор": "calc.exe",
    "calculator": "calc.exe",
    "проводник": "explorer.exe",
    "explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "командная строка": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "терминал": "wt.exe",
    "taskmgr": "taskmgr.exe",
    "диспетчер задач": "taskmgr.exe",
    "control": "control.exe",
    "панель управления": "control.exe",
    "regedit": "regedit.exe",
    "реестр": "regedit.exe",
    "mspaint": "mspaint.exe",
    "paint": "mspaint.exe",
    "snippingtool": "snippingtool.exe",
    "ножницы": "snippingtool.exe",
    "settings": "ms-settings:",
    "настройки": "ms-settings:",
    "telegram": "tg://",
    "телеграм": "tg://",
    "discord": "discord://",
    "дискорд": "discord://",
    "chrome": "chrome.exe",
    "хром": "chrome.exe",
    "гугл хром": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "яндекс": "browser.exe",
    "яндекс браузер": "browser.exe",
}


def _start_menu_shortcuts():
    roots = [
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
        Path(os.environ.get("PROGRAMDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
    ]
    for root in roots:
        if root.exists():
            yield from root.rglob("*.lnk")


def _find_shortcut(name):
    name = str(name or "").strip().lower()
    for shortcut in _start_menu_shortcuts():
        if name in shortcut.stem.lower():
            return shortcut
    return None


def _find_app_path(name):
    import winreg

    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    needle = str(name or "").strip().lower()
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as base:
                for index in range(winreg.QueryInfoKey(base)[0]):
                    try:
                        sub_name = winreg.EnumKey(base, index)
                        if needle in sub_name.lower():
                            with winreg.OpenKey(base, sub_name) as sub:
                                return winreg.QueryValueEx(sub, "")[0]
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def _launch(path, args=None, admin=False, wait=False, cwd=None):
    args = [str(item) for item in (args or [])]
    suffix = Path(str(path)).suffix.lower()
    if not args and not admin and not wait and suffix in {".lnk", ".url"}:
        os.startfile(str(path))
        return f"Запущено: {path}"
    if admin:
        import ctypes

        params = " ".join(args)
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(path),
            params,
            str(cwd) if cwd else None,
            1,
        )
        if result <= 32:
            return f"Не удалось запустить с правами администратора (код {result})."
        return f"Запущено с правами администратора: {path}"

    command = [str(path)] + args
    if wait:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.stdout or result.stderr or "Приложение завершено."

    process = subprocess.Popen(command, cwd=cwd)
    return f"Запущено: {path} (PID {process.pid})"


def _launch_uninstaller(command):
    """Запускает UninstallString без интерпретации cmd.exe.

    ``shell=True`` позволял внедрение через метасимволы (&, |, >) в
    реестровом значении. CreateProcess сам разбирает строку с
    кавычками; для .bat/.cmd нужен явный cmd.exe.
    """

    text = str(command or "").strip()
    if not text:
        return None
    head = text.split()[0].strip('"').lower()
    if head.endswith((".bat", ".cmd")):
        return subprocess.Popen(["cmd.exe", "/c", text])
    return subprocess.Popen(text)


_APPX_EXE_CACHE = {}


def _appx_executable(name, timeout=30):
    key = str(name or "").strip().lower()
    if not key:
        return None
    if key in _APPX_EXE_CACHE:
        return _APPX_EXE_CACHE[key]

    pattern = "*" + str(name).strip() + "*"
    script = (
        "$pkg = Get-AppxPackage | Where-Object { $_.Name -like "
        f"{ps_quote(pattern)} }} | Select-Object -First 1; "
        "if (-not $pkg) { exit 0 }; "
        "$manifest = $pkg | Get-AppxPackageManifest; "
        "$exe = $manifest.Package.Applications.Application | "
        "ForEach-Object { $_.Executable } | "
        "Where-Object { $_ } | Select-Object -First 1; "
        "if ($exe) { Join-Path $pkg.InstallLocation $exe }"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=max(5, int(timeout or 30)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        candidate = line.strip()
        if candidate and os.path.exists(candidate):
            _APPX_EXE_CACHE[key] = candidate
            return candidate
    return None


def launch_store_app(name, timeout=30):
    exe = _appx_executable(name, timeout=timeout)
    if exe:
        try:
            os.startfile(exe)
            activate_window(
                [name],
                timeout=4.0,
                process_names=[name],
            )
            return f"Запущено: {exe}"
        except OSError:
            pass

    pattern = "*" + str(name or "").strip() + "*"
    if pattern == "**":
        return None
    script = (
        "$app = Get-StartApps | "
        f"Where-Object {{ $_.Name -like {ps_quote(pattern)} }} | "
        "Select-Object -First 1 -ExpandProperty AppID; "
        "if ($app) { $app }"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=max(5, int(timeout or 30)),
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Не удалось найти приложение в меню Пуск."
            + (f" {detail[:300]}" if detail else "")
        )
    app_id = (result.stdout or "").strip()
    if not app_id:
        return None
    try:
        os.startfile(f"shell:AppsFolder\\{app_id}")
    except OSError:
        result = _launch(
            "explorer.exe",
            [f"shell:AppsFolder\\{app_id}"],
        )
        activate_window(
            [name],
            timeout=4.0,
            process_names=[name],
        )
        return result
    activate_window(
        [name],
        timeout=4.0,
        process_names=[name],
    )
    return f"Запущено: {app_id}"


def launch_by_name(name, args=None, admin=False, wait=False, cwd=None):
    name = str(name or "").strip()
    if not name:
        return "Не указано приложение."

    candidate = Path(os.path.expandvars(os.path.expanduser(name)))
    if candidate.exists():
        return _launch(candidate, args, admin, wait, cwd)

    alias = ALIASES.get(name.lower())

    if alias == "tg://":
        try:
            store_result = launch_store_app("Telegram")
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            store_result = None
        if store_result:
            return store_result

    if alias and ("://" in alias or alias.endswith(":")):
        try:
            os.startfile(alias)
        except OSError as error:
            return f"Не удалось открыть {alias}: {error}"
        return f"Открыто: {alias}"

    target = alias or name

    shortcut = (
        _find_shortcut(target)
        or _find_shortcut(Path(target).stem)
        or _find_shortcut(name)
        or _find_shortcut(Path(name).stem)
    )
    if shortcut:
        return _launch(shortcut, args, admin, wait, cwd)

    app_path = _find_app_path(target)
    if app_path:
        return _launch(app_path, args, admin, wait, cwd)

    found = shutil.which(target)
    if found:
        return _launch(found, args, admin, wait, cwd)

    if target.lower().endswith(".exe"):
        try:
            os.startfile(target)
            return f"Запущено: {target}"
        except OSError:
            pass

    if "://" in name or name.startswith("ms-"):
        try:
            os.startfile(name)
        except OSError as error:
            return f"Не удалось открыть {name}: {error}"
        return f"Открыт протокол: {name}"

    result = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Start-Process -FilePath {ps_quote(name)}",
        ],
        timeout=30,
    )
    if result.get("ok"):
        return f"Запущено через PowerShell: {name}"
    return (
        f"Приложение «{name}» не найдено. "
        "Можно указать полный путь."
    )


def register(registry):

    @registry.tool(
        "app_launch",
        "Запустить любое приложение по имени, пути, протоколу или ярлыку.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "args": {"type": "array"},
                "admin": {"type": "boolean"},
                "wait": {"type": "boolean"},
                "cwd": {"type": "string"},
            },
            "required": ["name"],
        },
        category="apps",
        danger="confirm",
    )
    def app_launch(name, args=None, admin=False, wait=False, cwd=None):
        return launch_by_name(
            name,
            args=args,
            admin=admin,
            wait=wait,
            cwd=cwd,
        )

    @registry.tool(
        "app_search",
        "Найти ярлыки приложений в меню Пуск.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="apps",
    )
    def app_search(query, limit=30):
        query = str(query or "").lower()
        results = []
        for shortcut in _start_menu_shortcuts():
            if query in shortcut.stem.lower():
                results.append(str(shortcut))
                if len(results) >= max(1, int(limit or 30)):
                    break
        return "\n".join(results) or "Ярлыки не найдены."

    @registry.tool(
        "app_close",
        "Закрыть приложение по имени процесса.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="apps",
        danger="dangerous",
    )
    def app_close(name):
        name = str(name or "").strip()
        if not name:
            return "Не указано приложение."
        process_name = name if name.lower().endswith(".exe") else name + ".exe"
        result = run_command(
            ["taskkill", "/F", "/IM", process_name],
            timeout=15,
        )
        return result["stdout"] or result["stderr"] or f"Приложение {name} закрыто."

    @registry.tool(
        "app_uninstall",
        "Удалить установленную программу через её деинсталлятор.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="apps",
        danger="dangerous",
    )
    def app_uninstall(name):
        import winreg

        needle = str(name or "").lower()
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for root, path in keys:
            try:
                with winreg.OpenKey(root, path) as base:
                    for index in range(winreg.QueryInfoKey(base)[0]):
                        try:
                            sub_name = winreg.EnumKey(base, index)
                            with winreg.OpenKey(base, sub_name) as sub:
                                display = winreg.QueryValueEx(sub, "DisplayName")[0]
                                if needle not in str(display).lower():
                                    continue
                                command = winreg.QueryValueEx(
                                    sub, "UninstallString"
                                )[0]
                                if _launch_uninstaller(command) is None:
                                    return "Команда удаления пуста."
                                return f"Запущен деинсталлятор: {display}"
                        except OSError:
                            continue
            except OSError:
                continue
        return f"Программа «{name}» не найдена."

    @registry.tool(
        "app_defaults",
        "Показать приложения по умолчанию.",
        {"type": "object", "properties": {}, "required": []},
        category="apps",
    )
    def app_defaults():
        return powershell(
            "Get-StartApps | Select-Object Name, AppID | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "app_association",
        "Показать, чем открывается расширение файла.",
        {
            "type": "object",
            "properties": {"extension": {"type": "string"}},
            "required": ["extension"],
        },
        category="apps",
    )
    def app_association(extension):
        extension = str(extension or "").strip()
        if not extension.startswith("."):
            extension = "." + extension
        return powershell(
            f"cmd /c assoc {ps_quote(extension)}; "
            f"cmd /c ftype",
            timeout=30,
        )

    @registry.tool(
        "app_version",
        "Показать версию установленной программы.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="apps",
    )
    def app_version(name):
        needle = str(name or "").lower()
        script = (
            "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, "
            "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, "
            "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
            "| Where-Object {$_.DisplayName -like '*" + needle + "*'} "
            "| Select-Object DisplayName, DisplayVersion, Publisher | "
            "Format-Table -AutoSize | Out-String"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "app_wait",
        "Дождаться появления процесса приложения.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["name"],
        },
        category="apps",
    )
    def app_wait(name, timeout=30):
        import psutil

        needle = str(name or "").lower()
        deadline = time.time() + max(1, int(timeout or 30))
        while time.time() < deadline:
            for process in psutil.process_iter(["name"]):
                try:
                    if needle in (process.info.get("name") or "").lower():
                        return (
                            f"Приложение {name} запущено, "
                            f"PID {process.pid}."
                        )
                except psutil.Error:
                    continue
            time.sleep(0.5)
        return f"Приложение {name} не появилось за {timeout} c."

    @registry.tool(
        "app_open_with",
        "Открыть файл указанной программой.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "program": {"type": "string"},
            },
            "required": ["path", "program"],
        },
        category="apps",
        danger="confirm",
    )
    def app_open_with(path, program):
        target = resolve_path(path, must_exist=True)
        return _launch(program, [str(target)])
