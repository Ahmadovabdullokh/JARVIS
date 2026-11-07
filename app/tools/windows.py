import time
from pathlib import Path

import pyautogui
import pygetwindow as gw

from app.tools.common import optional_import


def _find_window(title):
    title = str(title or "").strip()
    if not title:
        return None
    windows = gw.getWindowsWithTitle(title)
    return windows[0] if windows else None


def _win32():
    win32gui = optional_import("win32gui")
    win32con = optional_import("win32con")
    return win32gui, win32con


def register(registry):

    @registry.tool(
        "windows_list",
        "Список окон с заголовком, позицией и размером.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="windows",
    )
    def windows_list(limit=100):
        lines = []
        for window in gw.getAllWindows():
            title = (window.title or "").strip()
            if not title:
                continue
            lines.append(
                f"{title} | {window.left},{window.top} "
                f"{window.width}x{window.height} | "
                f"{'min' if window.isMinimized else 'max' if window.isMaximized else 'normal'}"
            )
            if len(lines) >= max(1, int(limit or 100)):
                break
        return "\n".join(lines) or "Открытых окон не найдено."

    @registry.tool(
        "window_active",
        "Информация об активном окне.",
        {"type": "object", "properties": {}, "required": []},
        category="windows",
    )
    def window_active():
        window = gw.getActiveWindow()
        if not window:
            return "Активное окно не найдено."
        return (
            f"Заголовок: {window.title}\n"
            f"Позиция: {window.left}, {window.top}\n"
            f"Размер: {window.width}x{window.height}\n"
            f"Свёрнуто: {window.isMinimized}, развёрнуто: {window.isMaximized}"
        )

    @registry.tool(
        "window_activate",
        "Активировать окно по части заголовка.",
        {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
        category="windows",
    )
    def window_activate(title):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        if window.isMinimized:
            window.restore()
        window.activate()
        return f"Активировано окно: {window.title}"

    @registry.tool(
        "window_close",
        "Закрыть окно по части заголовка.",
        {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
        category="windows",
        danger="confirm",
    )
    def window_close(title):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        window.close()
        return f"Закрыто окно: {title}"

    @registry.tool(
        "window_state",
        "Свернуть, развернуть или восстановить окно.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["minimize", "maximize", "restore"],
                },
            },
            "required": ["title", "action"],
        },
        category="windows",
    )
    def window_state(title, action):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        if action == "minimize":
            window.minimize()
        elif action == "maximize":
            window.maximize()
        else:
            window.restore()
        return f"Окно «{title}»: {action}."

    @registry.tool(
        "window_move_resize",
        "Переместить и/или изменить размер окна.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["title"],
        },
        category="windows",
    )
    def window_move_resize(title, x=None, y=None, width=None, height=None):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        if x is not None or y is not None:
            window.moveTo(
                int(x if x is not None else window.left),
                int(y if y is not None else window.top),
            )
        if width is not None or height is not None:
            window.resizeTo(
                int(width if width is not None else window.width),
                int(height if height is not None else window.height),
            )
        return f"Окно «{title}» изменено."

    @registry.tool(
        "window_snap",
        "Прикрепить окно к краю экрана.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "side": {
                    "type": "string",
                    "enum": ["left", "right", "top", "bottom", "center"],
                },
            },
            "required": ["title", "side"],
        },
        category="windows",
    )
    def window_snap(title, side):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        width, height = pyautogui.size()
        if side == "left":
            window.moveTo(0, 0)
            window.resizeTo(width // 2, height)
        elif side == "right":
            window.moveTo(width // 2, 0)
            window.resizeTo(width // 2, height)
        elif side == "top":
            window.moveTo(0, 0)
            window.resizeTo(width, height // 2)
        elif side == "bottom":
            window.moveTo(0, height // 2)
            window.resizeTo(width, height // 2)
        else:
            window.moveTo(0, 0)
            window.resizeTo(width, height)
        return f"Окно «{title}» прикреплено: {side}."

    @registry.tool(
        "window_topmost",
        "Включить или выключить режим поверх всех окон.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["title", "enabled"],
        },
        category="windows",
    )
    def window_topmost(title, enabled=True):
        win32gui, win32con = _win32()
        if win32gui is None:
            return "Для этой функции нужен pywin32."
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        handle = win32gui.FindWindow(None, window.title)
        win32gui.SetWindowPos(
            handle,
            win32con.HWND_TOPMOST if enabled else win32con.HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
        return f"Поверх всех окон: {enabled}."

    @registry.tool(
        "window_opacity",
        "Установить прозрачность окна от 0 до 255.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "opacity": {"type": "integer"},
            },
            "required": ["title", "opacity"],
        },
        category="windows",
    )
    def window_opacity(title, opacity):
        win32gui, win32con = _win32()
        if win32gui is None:
            return "Для этой функции нужен pywin32."
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        handle = win32gui.FindWindow(None, window.title)
        value = max(0, min(int(opacity), 255))
        win32gui.SetWindowLong(
            handle,
            win32con.GWL_EXSTYLE,
            win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
            | win32con.WS_EX_LAYERED,
        )
        win32gui.SetLayeredWindowAttributes(
            handle,
            0,
            value,
            win32con.LWA_ALPHA,
        )
        return f"Прозрачность окна «{title}»: {value}/255."

    @registry.tool(
        "window_screenshot",
        "Сделать снимок окна по заголовку.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["title"],
        },
        category="windows",
    )
    def window_screenshot(title, path=None):
        window = _find_window(title)
        if window is None:
            return f"Окно «{title}» не найдено."
        if window.isMinimized:
            window.restore()
        window.activate()
        time.sleep(0.3)
        image = pyautogui.screenshot(
            region=(
                window.left,
                window.top,
                window.width,
                window.height,
            )
        )
        output = Path(path or f"window_{int(time.time())}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        return f"Снимок окна сохранён: {output}"

    @registry.tool(
        "monitors_info",
        "Информация о мониторах и разрешении.",
        {"type": "object", "properties": {}, "required": []},
        category="windows",
    )
    def monitors_info():
        width, height = pyautogui.size()
        try:
            monitors = pyautogui.getMonitors() if hasattr(pyautogui, "getMonitors") else []
        except Exception:
            monitors = []
        lines = [f"Основной экран: {width}x{height}"]
        for index, monitor in enumerate(monitors, start=1):
            lines.append(f"Монитор {index}: {monitor}")
        return "\n".join(lines)

    @registry.tool(
        "virtual_desktops",
        "Показать виртуальные рабочие столы Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="windows",
    )
    def virtual_desktops():
        win32gui, win32con = _win32()
        if win32gui is None:
            return "Для этой функции нужен pywin32."
        try:

            return (
                "Управление виртуальными столами доступно через "
                "Win+Ctrl+D (создать), Win+Ctrl+Left/Right (переключить), "
                "Win+Ctrl+F4 (закрыть)."
            )
        except Exception as error:
            return f"Не удалось получить виртуальные столы: {error}"
