import time

import pyautogui
import pyperclip


def _safe(action):
    try:
        return action()
    except pyautogui.FailSafeException:
        return "Сработала защита pyautogui: курсор в углу экрана."
    except Exception as error:
        return f"Ошибка ввода: {error}"


def _paste_text(text):
    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(str(text))
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)
    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass


def register(registry):

    @registry.tool(
        "mouse_move",
        "Переместить курсор мыши.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration": {"type": "number"},
            },
            "required": ["x", "y"],
        },
        category="input",
    )
    def mouse_move(x, y, duration=0.2):
        return _safe(
            lambda: pyautogui.moveTo(
                int(x), int(y), duration=float(duration or 0)
            )
            or f"Курсор перемещён в {x}, {y}."
        )

    @registry.tool(
        "mouse_position",
        "Показать текущую позицию курсора.",
        {"type": "object", "properties": {}, "required": []},
        category="input",
    )
    def mouse_position():
        position = pyautogui.position()
        return f"Курсор: {position.x}, {position.y}"

    @registry.tool(
        "mouse_click",
        "Кликнуть мышью.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                },
                "clicks": {"type": "integer"},
                "interval": {"type": "number"},
            },
            "required": [],
        },
        category="input",
        danger="confirm",
    )
    def mouse_click(x=None, y=None, button="left", clicks=1, interval=0.1):
        def action():
            if x is not None and y is not None:
                pyautogui.moveTo(int(x), int(y), duration=0.1)
            pyautogui.click(
                button=button,
                clicks=max(1, int(clicks or 1)),
                interval=float(interval or 0.1),
            )
            return f"Клик: {button} x{clicks}."

        return _safe(action)

    @registry.tool(
        "mouse_drag",
        "Перетащить мышью из одной точки в другую.",
        {
            "type": "object",
            "properties": {
                "x1": {"type": "integer"},
                "y1": {"type": "integer"},
                "x2": {"type": "integer"},
                "y2": {"type": "integer"},
                "duration": {"type": "number"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                },
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
        category="input",
        danger="confirm",
    )
    def mouse_drag(x1, y1, x2, y2, duration=0.5, button="left"):
        def action():
            pyautogui.moveTo(int(x1), int(y1), duration=0.1)
            pyautogui.dragTo(
                int(x2),
                int(y2),
                duration=float(duration or 0.5),
                button=button,
            )
            return f"Перетащено из {x1},{y1} в {x2},{y2}."

        return _safe(action)

    @registry.tool(
        "mouse_scroll",
        "Прокрутить колесо мыши.",
        {
            "type": "object",
            "properties": {
                "amount": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["amount"],
        },
        category="input",
    )
    def mouse_scroll(amount, x=None, y=None):
        def action():
            if x is not None and y is not None:
                pyautogui.moveTo(int(x), int(y), duration=0.1)
            pyautogui.scroll(int(amount))
            return f"Прокрутка: {amount}."

        return _safe(action)

    @registry.tool(
        "keyboard_type",
        "Напечатать текст (латиница и спецсимволы).",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "interval": {"type": "number"},
            },
            "required": ["text"],
        },
        category="input",
        danger="confirm",
    )
    def keyboard_type(text, interval=0.02):
        return _safe(
            lambda: pyautogui.write(
                str(text), interval=float(interval or 0.02)
            )
            or f"Напечатано {len(str(text))} символов."
        )

    @registry.tool(
        "text_type",
        "Вставить произвольный текст, включая кириллицу, через буфер обмена.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        category="input",
        danger="confirm",
    )
    def text_type(text):
        return _safe(
            lambda: _paste_text(text)
            or f"Вставлен текст из {len(str(text))} символов."
        )

    @registry.tool(
        "keyboard_hotkey",
        "Нажать сочетание клавиш, например ctrl+shift+esc.",
        {
            "type": "object",
            "properties": {
                "keys": {"type": "array"},
                "interval": {"type": "number"},
            },
            "required": ["keys"],
        },
        category="input",
        danger="confirm",
    )
    def keyboard_hotkey(keys, interval=0.05):
        def action():
            pyautogui.hotkey(
                *[str(key) for key in keys],
                interval=float(interval or 0.05),
            )
            return "Нажато: " + "+".join(str(key) for key in keys)

        return _safe(action)

    @registry.tool(
        "keyboard_press",
        "Нажать и отпустить одну клавишу несколько раз.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "presses": {"type": "integer"},
                "interval": {"type": "number"},
            },
            "required": ["key"],
        },
        category="input",
        danger="confirm",
    )
    def keyboard_press(key, presses=1, interval=0.05):
        def action():
            pyautogui.press(
                str(key),
                presses=max(1, int(presses or 1)),
                interval=float(interval or 0.05),
            )
            return f"Нажата клавиша {key} x{presses}."

        return _safe(action)

    @registry.tool(
        "keyboard_hold",
        "Зажать клавишу на указанное время.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "duration": {"type": "number"},
            },
            "required": ["key"],
        },
        category="input",
        danger="confirm",
    )
    def keyboard_hold(key, duration=1.0):
        def action():
            pyautogui.keyDown(str(key))
            time.sleep(max(0.05, float(duration or 1.0)))
            pyautogui.keyUp(str(key))
            return f"Клавиша {key} удерживалась {duration} c."

        return _safe(action)

    @registry.tool(
        "clipboard_get",
        "Прочитать текст из буфера обмена.",
        {"type": "object", "properties": {}, "required": []},
        category="input",
    )
    def clipboard_get():
        return pyperclip.paste() or "(буфер обмена пуст)"

    @registry.tool(
        "clipboard_set",
        "Записать текст в буфер обмена.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        category="input",
    )
    def clipboard_set(text):
        pyperclip.copy(str(text))
        return f"В буфер обмена записано {len(str(text))} символов."

    @registry.tool(
        "clipboard_clear",
        "Очистить буфер обмена.",
        {"type": "object", "properties": {}, "required": []},
        category="input",
    )
    def clipboard_clear():
        pyperclip.copy("")
        return "Буфер обмена очищен."

    @registry.tool(
        "screen_lock",
        "Заблокировать компьютер.",
        {"type": "object", "properties": {}, "required": []},
        category="input",
        danger="confirm",
    )
    def screen_lock():
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return "Компьютер заблокирован."
