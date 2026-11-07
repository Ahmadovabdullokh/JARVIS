import json
import threading
import time

from app.tools.common import (
    BASE_DIR,
    optional_import,
    powershell,
    ps_quote,
    resolve_path,
)

DATA_DIR = BASE_DIR / "data"
WORKFLOWS = DATA_DIR / "workflows.json"


def _load_workflows():
    if not WORKFLOWS.exists():
        return {}
    try:
        return json.loads(WORKFLOWS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_workflows(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKFLOWS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register(registry):

    @registry.tool(
        "workflow_save",
        "Сохранить последовательность инструментов как сценарий.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "steps": {"type": "array"},
            },
            "required": ["name", "steps"],
        },
        category="automation",
    )
    def workflow_save(name, steps):
        workflows = _load_workflows()
        workflows[str(name)] = list(steps or [])
        _save_workflows(workflows)
        return f"Сценарий «{name}» сохранён ({len(steps or [])} шагов)."

    @registry.tool(
        "workflow_list",
        "Показать сохранённые сценарии.",
        {"type": "object", "properties": {}, "required": []},
        category="automation",
    )
    def workflow_list():
        workflows = _load_workflows()
        if not workflows:
            return "Сценариев нет."
        lines = []
        for name, steps in workflows.items():
            lines.append(f"{name}: {len(steps)} шагов")
        return "\n".join(lines)

    @registry.tool(
        "workflow_run",
        "Выполнить сценарий или список шагов.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "steps": {"type": "array"},
                "stop_on_error": {"type": "boolean"},
            },
            "required": [],
        },
        category="automation",
        danger="confirm",
    )
    def workflow_run(name=None, steps=None, stop_on_error=True):
        if name:
            steps = _load_workflows().get(str(name))
            if steps is None:
                return f"Сценарий «{name}» не найден."
        results = []
        for index, step in enumerate(steps or [], start=1):
            if not isinstance(step, dict):
                results.append(f"{index}. пропуск: шаг не объект")
                continue
            tool = step.get("tool") or step.get("name")
            arguments = step.get("arguments") or step.get("args") or {}
            delay = step.get("delay")
            if delay:
                time.sleep(float(delay))
            if not tool:
                results.append(f"{index}. пропуск: нет tool")
                continue
            output = registry.execute(str(tool), arguments)
            results.append(f"{index}. {tool}: {output[:500]}")
            if stop_on_error and (
                "Ошибка" in output or "Таймаут" in output
            ):
                break
        return "\n".join(results) or "Нет шагов."

    @registry.tool(
        "workflow_delete",
        "Удалить сохранённый сценарий.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="automation",
        danger="confirm",
    )
    def workflow_delete(name):
        workflows = _load_workflows()
        if str(name) in workflows:
            del workflows[str(name)]
            _save_workflows(workflows)
            return f"Сценарий «{name}» удалён."
        return "Сценарий не найден."

    @registry.tool(
        "automation_run_sequence",
        "Выполнить инструменты по очереди с задержками.",
        {
            "type": "object",
            "properties": {
                "steps": {"type": "array"},
                "delay": {"type": "number"},
            },
            "required": ["steps"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_run_sequence(steps, delay=0):
        results = []
        for index, step in enumerate(steps or [], start=1):
            if isinstance(step, dict):
                tool = step.get("tool") or step.get("name")
                arguments = step.get("arguments") or {}
            elif isinstance(step, str):
                tool = step
                arguments = {}
            else:
                continue
            if not tool:
                continue
            output = registry.execute(str(tool), arguments)
            results.append(f"{index}. {tool}: {output[:300]}")
            if delay:
                time.sleep(float(delay))
        return "\n".join(results) or "Нет шагов."

    @registry.tool(
        "automation_schedule",
        "Запланировать выполнение сценария по расписанию.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "steps": {"type": "array"},
                "when": {"type": "string"},
                "every": {"type": "string"},
            },
            "required": ["name"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_schedule(name, steps=None, when=None, every=None):
        schedule = optional_import("schedule")
        if schedule is None:
            return "Для расписания установите schedule."
        if steps is None:
            steps = _load_workflows().get(str(name))
        if not steps:
            return "Нет шагов для выполнения."
        job = schedule.every()

        def worker():
            registry.execute("workflow_run", {"name": name, "steps": steps})

        if every:
            text = str(every).strip().lower()
            if text.endswith("seconds"):
                job = schedule.every(int(text.split()[0])).seconds
            elif text.endswith("minutes"):
                job = schedule.every(int(text.split()[0])).minutes
            elif text.endswith("hours"):
                job = schedule.every(int(text.split()[0])).hours
            elif text.endswith("days"):
                job = schedule.every(int(text.split()[0])).days
            else:
                return "Формат every: 10 seconds / 5 minutes / 2 hours."
            job.do(worker)
        elif when:
            job = schedule.every().day.at(str(when))
            job.do(worker)
        else:
            return "Укажите every или when (HH:MM)."

        def runner():
            while True:
                schedule.run_pending()
                time.sleep(1)

        threading.Thread(target=runner, daemon=True).start()
        return f"Сценарий «{name}» запланирован."

    @registry.tool(
        "automation_wait",
        "Подождать указанное количество секунд.",
        {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
        category="automation",
    )
    def automation_wait(seconds=1):
        delay = max(0, float(seconds or 1))
        time.sleep(delay)
        return f"Ожидание {delay} c завершено."

    @registry.tool(
        "automation_wait_window",
        "Дождаться появления окна.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["title"],
        },
        category="automation",
    )
    def automation_wait_window(title, timeout=30):
        import pygetwindow as gw

        deadline = time.time() + max(1, float(timeout or 30))
        while time.time() < deadline:
            if gw.getWindowsWithTitle(str(title)):
                return f"Окно «{title}» найдено."
            time.sleep(0.5)
        return f"Окно «{title}» не появилось."

    @registry.tool(
        "automation_wait_image",
        "Дождаться появления изображения на экране.",
        {
            "type": "object",
            "properties": {
                "template": {"type": "string"},
                "timeout": {"type": "number"},
                "confidence": {"type": "number"},
            },
            "required": ["template"],
        },
        category="automation",
    )
    def automation_wait_image(template, timeout=30, confidence=0.8):
        import pyautogui

        deadline = time.time() + max(1, float(timeout or 30))
        while time.time() < deadline:
            try:
                location = pyautogui.locateOnScreen(
                    str(template),
                    confidence=float(confidence or 0.8),
                )
            except Exception:
                location = None
            if location:
                return f"Изображение найдено: {location}"
            time.sleep(0.5)
        return "Изображение не появилось."

    @registry.tool(
        "automation_startup_add",
        "Добавить программу в автозагрузку.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["name", "command"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_startup_add(name, command):
        script = (
            "New-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
            f"-Name {ps_quote(name)} -Value {ps_quote(command)} "
            "-PropertyType String -Force"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "automation_startup_remove",
        "Убрать программу из автозагрузки.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_startup_remove(name):
        script = (
            "Remove-ItemProperty -Path "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
            f"-Name {ps_quote(name)} -ErrorAction SilentlyContinue"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "automation_task_create",
        "Создать задачу в Планировщике Windows.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
                "time": {"type": "string"},
                "daily": {"type": "boolean"},
            },
            "required": ["name", "command"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_task_create(name, command, time="09:00", daily=True):
        schedule = "DAILY" if daily else "ONCE"
        script = (
            f"schtasks /Create /TN {ps_quote(name)} "
            f"/TR {ps_quote(command)} /SC {schedule} /ST {ps_quote(time)} /F"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "automation_task_delete",
        "Удалить задачу Планировщика Windows.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        category="automation",
        danger="dangerous",
    )
    def automation_task_delete(name):
        return powershell(
            f"schtasks /Delete /TN {ps_quote(name)} /F",
            timeout=60,
        )

    @registry.tool(
        "automation_watch_folder",
        "Следить за изменениями в папке.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "seconds": {"type": "number"},
            },
            "required": ["path"],
        },
        category="automation",
    )
    def automation_watch_folder(path, seconds=10):
        watchdog = optional_import("watchdog.events")
        observer_module = optional_import("watchdog.observers")
        if watchdog is None or observer_module is None:
            return "Для наблюдения за папкой установите watchdog."
        folder = resolve_path(path, must_exist=True)
        events = []

        class Handler(watchdog.FileSystemEventHandler):
            def on_any_event(self, event):
                events.append(
                    f"{event.event_type}: {event.src_path}"
                )

        observer = observer_module.Observer()
        observer.schedule(Handler(), str(folder), recursive=True)
        observer.start()
        time.sleep(max(1, float(seconds or 10)))
        observer.stop()
        observer.join()
        return "\n".join(events[:200]) or "Изменений не было."

    @registry.tool(
        "automation_copilot_fix",
        "Открыть проект в VS Code и передать задание в "
        "GitHub Copilot Chat, затем проверить результат OCR.",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "prompt": {"type": "string"},
                "open": {"type": "boolean"},
                "window_title": {"type": "string"},
                "chat_hotkey": {"type": "array"},
                "send_key": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["project", "prompt"],
        },
        category="automation",
        danger="confirm",
    )
    def automation_copilot_fix(
        project,
        prompt,
        open=True,
        window_title="Visual Studio Code",
        chat_hotkey=None,
        send_key="enter",
        timeout=60,
    ):
        import shutil as _shutil
        import subprocess as _subprocess

        import pyautogui
        import pygetwindow as gw
        import pyperclip

        if not str(prompt or "").strip():
            return "Ошибка: пустое задание для Copilot."
        if chat_hotkey is None:
            chat_hotkey = ["ctrl", "alt", "i"]

        steps = []
        target = resolve_path(project)
        if open:
            if target.exists():
                code_path = _shutil.which("code")
                if code_path:
                    _subprocess.Popen(
                        [code_path, str(target)],
                        shell=False,
                    )
                else:
                    output = registry.execute(
                        "app_launch",
                        {"name": "Visual Studio Code"},
                    )
                    steps.append(f"запуск: {output[:200]}")
            else:
                steps.append(
                    f"предупреждение: путь {target} не найден, "
                    "открываю только VS Code"
                )
                code_path = _shutil.which("code")
                if code_path:
                    _subprocess.Popen([code_path])
                else:
                    registry.execute(
                        "app_launch",
                        {"name": "Visual Studio Code"},
                    )

        deadline = time.time() + max(10, float(timeout or 60))
        window = None
        while time.time() < deadline:
            windows = gw.getWindowsWithTitle(
                str(window_title or "Visual Studio")
            )
            if windows:
                window = windows[0]
                break
            time.sleep(0.5)
        if window is None:
            return "\n".join(steps + [
                "Ошибка: окно VS Code не появилось."
            ])
        if window.isMinimized:
            window.restore()
        window.activate()
        steps.append(f"окно: {window.title}")
        time.sleep(1.0)

        keys = [str(key) for key in (chat_hotkey or [])]
        if keys:
            pyautogui.hotkey(*keys)
            steps.append("горячая клавиша чата: " + "+".join(keys))
            time.sleep(1.5)

        previous = None
        try:
            previous = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(str(prompt))
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        if previous is not None:
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
        steps.append(f"вставлено задание ({len(str(prompt))} симв.)")

        if str(send_key or "").strip():
            pyautogui.press(str(send_key))
            steps.append(f"отправка: {send_key}")
            time.sleep(6.0)

        ocr_result = registry.execute("screen_ocr", {})
        steps.append(
            "проверка экрана: " + str(ocr_result)[:500]
        )
        return "\n".join(steps)
