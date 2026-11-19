import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from app.paths import BASE_DIR  # noqa: F401  (re-export для инструментов)


def optional_import(module_name):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def resolve_path(path, base=None, must_exist=False):
    text = str(path or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("Путь не указан.")
    text = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = Path(base or Path.home()) / candidate
    candidate = candidate.resolve()
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Путь не найден: {candidate}")
    return candidate


def human_size(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(size) < 1024.0 or unit == "ТБ":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ТБ"


def truncate(text, limit=12000, suffix="\n…[обрезано]"):
    text = str(text or "")
    limit = int(limit or 0)
    if limit > 0 and len(text) > limit:
        return text[:limit] + suffix
    return text


def run_command(
    args,
    timeout=120,
    cwd=None,
    shell=False,
    input_text=None,
    env=None,
):
    if isinstance(args, str) and not shell:
        args = shlex.split(args, posix=False)
    started = time.time()
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "elapsed": round(time.time() - started, 3),
            "command": args if isinstance(args, str) else " ".join(map(str, args)),
        }
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": (error.stdout or "") if isinstance(error.stdout, str) else "",
            "stderr": f"Таймаут {timeout} c.",
            "elapsed": round(time.time() - started, 3),
            "command": args if isinstance(args, str) else " ".join(map(str, args)),
        }
    except Exception as error:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
            "elapsed": round(time.time() - started, 3),
            "command": args if isinstance(args, str) else " ".join(map(str, args)),
        }


def format_command_result(result):
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"].strip())
    if result.get("stderr"):
        parts.append("[stderr] " + result["stderr"].strip())
    if not parts:
        parts.append(
            f"Код возврата: {result.get('returncode')}"
        )
    return "\n".join(parts)


def powershell(script, timeout=120, cwd=None):
    result = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            str(script),
        ],
        timeout=timeout,
        cwd=cwd,
    )
    return format_command_result(result)


def powershell_json(script, timeout=120, cwd=None):
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        + str(script)
    )
    result = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        timeout=timeout,
        cwd=cwd,
    )
    if not result.get("ok"):
        return None
    text = (result.get("stdout") or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_path(path):
    os.startfile(str(path))
    return f"Открыл: {path}"


def _command_executable(command):
    text = str(command or "").strip()
    if not text:
        return None
    match = re.match(r'^\s*"([^"]+)"', text)
    candidate = match.group(1) if match else text.split()[0]
    candidate = os.path.expandvars(candidate)
    if os.path.exists(candidate):
        return candidate
    return None


def _browser_executables():
    commands = []
    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg is not None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\https\UserChoice",
            ) as key:
                prog_id = str(winreg.QueryValueEx(key, "ProgId")[0])
        except OSError:
            prog_id = ""

        if prog_id:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT,
                    f"{prog_id}\\shell\\open\\command",
                ) as key:
                    commands.append(winreg.QueryValueEx(key, "")[0])
            except OSError:
                pass

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    root,
                    r"SOFTWARE\Clients\StartMenuInternet",
                ) as base:
                    count = winreg.QueryInfoKey(base)[0]
                    for index in range(count):
                        try:
                            client = winreg.EnumKey(base, index)
                            with winreg.OpenKey(
                                base,
                                f"{client}\\shell\\open\\command",
                            ) as key:
                                commands.append(
                                    winreg.QueryValueEx(key, "")[0]
                                )
                        except OSError:
                            continue
            except OSError:
                continue

    executables = []
    for command in commands:
        exe = _command_executable(command)
        if exe and exe not in executables:
            executables.append(exe)

    for name in (
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "opera.exe",
        "brave.exe",
        "browser.exe",
    ):
        found = shutil.which(name)
        if found and found not in executables:
            executables.append(found)

    for path in (
        r"%ProgramFiles%\Yandex\YandexBrowser\Application\browser.exe",
        r"%ProgramFiles(x86)%\Yandex\YandexBrowser\Application\browser.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
        r"%LocalAppData%\Programs\Opera\opera.exe",
        r"%ProgramFiles%\Opera\opera.exe",
    ):
        expanded = os.path.expandvars(path)
        if os.path.exists(expanded) and expanded not in executables:
            executables.append(expanded)

    return executables


def activate_window(
    title_hints,
    timeout=5.0,
    interval=0.15,
    process_names=None,
):
    hints = [
        str(hint).strip().lower()
        for hint in (title_hints or [])
        if str(hint).strip()
    ]
    names = {
        str(name).strip().lower().removesuffix(".exe")
        for name in (process_names or [])
        if str(name).strip()
    }
    if not hints and not names:
        return False

    win32gui = optional_import("win32gui")
    win32con = optional_import("win32con")
    if win32gui is None or win32con is None:
        return False
    win32process = optional_import("win32process")
    psutil = optional_import("psutil")

    def _process_name(hwnd):
        if win32process is None or psutil is None:
            return ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = psutil.Process(pid).name().lower()
            return name.removesuffix(".exe")
        except Exception:
            return ""

    def _scan(predicate):
        visible = []
        hidden = []

        def _collect(hwnd, _extra):
            try:
                title = win32gui.GetWindowText(hwnd) or ""
                if not title:
                    return True
                if not predicate(hwnd, title):
                    return True
                if win32gui.IsWindowVisible(hwnd):
                    visible.append(hwnd)
                else:
                    hidden.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_collect, None)
        except Exception:
            return []
        return visible or hidden

    deadline = time.time() + max(0.0, float(timeout))
    while True:
        matched = []
        if names:
            matched = _scan(
                lambda hwnd, _title: _process_name(hwnd) in names
            )
        if not matched and hints:
            matched = _scan(
                lambda _hwnd, title: any(
                    hint in title.lower() for hint in hints
                )
            )

        if matched:
            hwnd = matched[0]
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.BringWindowToTop(hwnd)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags
                    )
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags
                    )
            except Exception:
                return False
            return True

        if time.time() >= deadline:
            return False
        time.sleep(max(0.05, float(interval)))


def _url_window_hints(url):
    try:
        parsed = urllib.parse.urlparse(
            url if "://" in url else "https://" + str(url)
        )
    except ValueError:
        return []
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return []
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 3 and parts[0] in {"www", "m", "mobile"}:
        parts = parts[1:]
    if len(parts) < 2:
        return []
    label = parts[-2]
    if label in {"co", "com", "org", "net", "gov", "edu", "ac"}:
        label = parts[-3] if len(parts) >= 3 else label
    return [label] if len(label) >= 4 else []


def open_url(url, window_titles=None, focus_timeout=3.0):
    text = str(url or "").strip()
    if not text:
        return False
    if "://" not in text and not text.startswith(
        ("about:", "mailto:", "tel:", "file:")
    ):
        text = "https://" + text

    hints = []
    for hint in list(window_titles or []) + _url_window_hints(text):
        value = str(hint or "").strip()
        if value and value not in hints:
            hints.append(value)

    for exe in _browser_executables():
        try:
            subprocess.Popen([exe, text], close_fds=True)
        except OSError:
            continue
        if hints:
            activate_window(hints, timeout=focus_timeout)
        return True

    try:
        subprocess.Popen(["explorer.exe", text])
        if hints:
            activate_window(hints, timeout=focus_timeout)
        return True
    except OSError:
        pass

    import webbrowser

    try:
        opened = bool(webbrowser.open(text))
    except Exception:
        return False
    if opened and hints:
        activate_window(hints, timeout=focus_timeout)
    return opened


def load_json_file(path, default=None):
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return default


def save_json_file(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    temp.replace(path)
    return str(path)


def notify(title, message):
    title = str(title or "JARVIS")
    message = str(message or "")
    winotify = optional_import("winotify")
    if winotify is not None:
        try:
            toast = winotify.Notification(
                app_id="JARVIS",
                title=title,
                msg=message,
            )
            toast.show()
            return "Уведомление отправлено."
        except Exception:
            pass
    try:
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]"
            "::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$text = $template.GetElementsByTagName('text'); "
            f"$text.Item(0).AppendChild($template.CreateTextNode({ps_quote(title)})) > $null; "
            f"$text.Item(1).AppendChild($template.CreateTextNode({ps_quote(message)})) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('JARVIS').Show($toast);"
        )
        powershell(script, timeout=15)
        return "Уведомление отправлено."
    except Exception as error:
        print(f"[NOTIFY] {title}: {message} ({error})")
        return f"Уведомление: {title} — {message}"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def default_shell():
    return "powershell.exe" if sys.platform == "win32" else "bash"
