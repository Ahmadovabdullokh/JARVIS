import importlib
import json
import os
import shlex
import subprocess
import sys
import time
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
