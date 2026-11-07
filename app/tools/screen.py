import base64
import io
import time
from pathlib import Path

import pyautogui
from PIL import Image, ImageGrab

from app.tools.common import optional_import


def _region(x, y, width, height):
    if None in (x, y, width, height):
        return None
    return (int(x), int(y), int(width), int(height))


def _grab(x=None, y=None, width=None, height=None, all_screens=False):
    region = _region(x, y, width, height)
    try:
        if all_screens:
            return ImageGrab.grab(all_screens=True)
        return ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    except Exception:
        return pyautogui.screenshot(region=region)


def _save(image, path=None, prefix="screen"):
    output = Path(path or f"{prefix}_{int(time.time())}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def register(registry):

    @registry.tool(
        "screen_capture",
        "Сделать снимок экрана или его части.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "all_screens": {"type": "boolean"},
            },
            "required": [],
        },
        category="screen",
    )
    def screen_capture(
        path=None,
        x=None,
        y=None,
        width=None,
        height=None,
        all_screens=False,
    ):
        image = _grab(x, y, width, height, all_screens)
        output = _save(image, path)
        return f"Снимок сохранён: {output} ({image.width}x{image.height})"

    @registry.tool(
        "screen_size",
        "Размер экрана в пикселях.",
        {"type": "object", "properties": {}, "required": []},
        category="screen",
    )
    def screen_size():
        width, height = pyautogui.size()
        return f"{width}x{height}"

    @registry.tool(
        "screen_pixel",
        "Цвет пикселя в указанной точке.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
        category="screen",
    )
    def screen_pixel(x, y):
        image = _grab()
        color = image.getpixel((int(x), int(y)))
        return f"Пиксель ({x}, {y}): RGB{color[:3]}"

    @registry.tool(
        "screen_ocr",
        "Распознать текст на экране или в его части.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "language": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": [],
        },
        category="screen",
    )
    def screen_ocr(
        x=None,
        y=None,
        width=None,
        height=None,
        language="rus+eng",
        path=None,
    ):
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            return "Для OCR установите pytesseract и Tesseract-OCR."
        image = _grab(x, y, width, height)
        if path:
            image = Image.open(path)
        try:
            text = pytesseract.image_to_string(image, lang=language)
        except Exception as error:
            return f"OCR не удался: {error}"
        return text.strip() or "Текст не распознан."

    @registry.tool(
        "screen_find_image",
        "Найти изображение на экране и вернуть координаты.",
        {
            "type": "object",
            "properties": {
                "template": {"type": "string"},
                "confidence": {"type": "number"},
                "grayscale": {"type": "boolean"},
            },
            "required": ["template"],
        },
        category="screen",
    )
    def screen_find_image(template, confidence=0.8, grayscale=False):
        try:
            location = pyautogui.locateOnScreen(
                str(template),
                confidence=float(confidence or 0.8),
                grayscale=bool(grayscale),
            )
        except Exception as error:
            return f"Поиск не удался: {error}"
        if not location:
            return "Изображение не найдено."
        center = pyautogui.center(location)
        return f"Найдено: {location} | центр {center.x}, {center.y}"

    @registry.tool(
        "screen_click_text",
        "Найти текст на экране через OCR и нажать на него.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "language": {"type": "string"},
                "confidence": {"type": "number"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "button": {"type": "string"},
                "clicks": {"type": "integer"},
                "all_screens": {"type": "boolean"},
            },
            "required": ["text"],
        },
        category="screen",
        danger="confirm",
    )
    def screen_click_text(
        text,
        language="rus+eng",
        confidence=30,
        x=None,
        y=None,
        width=None,
        height=None,
        button="left",
        clicks=1,
        all_screens=False,
    ):
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            return "Для OCR установите pytesseract и Tesseract-OCR."
        needle = str(text or "").strip().lower()
        if not needle:
            return "Не указан текст для поиска."
        image = _grab(x, y, width, height, all_screens)
        offset_x = int(x or 0)
        offset_y = int(y or 0)
        try:
            data = pytesseract.image_to_data(
                image,
                lang=language,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as error:
            return f"OCR не удался: {error}"

        words = []
        for index, value in enumerate(data.get("text", [])):
            value = str(value or "").strip().lower()
            if not value:
                continue
            try:
                score = float(data["conf"][index])
            except (KeyError, TypeError, ValueError):
                score = 0
            if score < float(confidence or 30):
                continue
            left = offset_x + int(data["left"][index])
            top = offset_y + int(data["top"][index])
            word_width = int(data["width"][index])
            word_height = int(data["height"][index])
            words.append(
                (
                    value,
                    left,
                    top,
                    word_width,
                    word_height,
                )
            )

        for word, left, top, word_width, word_height in words:
            if needle not in word and word not in needle:
                continue
            center_x = left + word_width // 2
            center_y = top + word_height // 2
            pyautogui.click(
                center_x,
                center_y,
                clicks=max(1, int(clicks or 1)),
                button=str(button or "left"),
            )
            return (
                f"Нажатие по тексту «{word}» в точке "
                f"({center_x}, {center_y})."
            )

        return f"Текст «{text}» на экране не найден."

    @registry.tool(
        "screen_record",
        "Записать видео с экрана.",
        {
            "type": "object",
            "properties": {
                "duration": {"type": "number"},
                "fps": {"type": "number"},
                "path": {"type": "string"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["duration"],
        },
        category="screen",
    )
    def screen_record(
        duration=5,
        fps=15,
        path=None,
        x=None,
        y=None,
        width=None,
        height=None,
    ):
        cv2 = optional_import("cv2")
        numpy = optional_import("numpy")
        if cv2 is None or numpy is None:
            return "Для записи экрана установите opencv-python и numpy."
        output = Path(path or f"recording_{int(time.time())}.mp4")
        output.parent.mkdir(parents=True, exist_ok=True)
        first = _grab(x, y, width, height)
        size = (first.width, first.height)
        writer = cv2.VideoWriter(
            str(output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(fps or 15),
            size,
        )
        frames = 0
        deadline = time.time() + max(1, float(duration or 5))
        interval = 1.0 / max(1, float(fps or 15))
        while time.time() < deadline:
            started = time.time()
            image = _grab(x, y, width, height)
            frame = numpy.array(image.convert("RGB"))
            writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            frames += 1
            elapsed = time.time() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)
        writer.release()
        return f"Запись сохранена: {output} ({frames} кадров)"

    @registry.tool(
        "screen_zoom",
        "Вырезать и увеличить область экрана.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "scale": {"type": "number"},
                "path": {"type": "string"},
            },
            "required": ["x", "y", "width", "height"],
        },
        category="screen",
    )
    def screen_zoom(x, y, width, height, scale=2, path=None):
        image = _grab(x, y, width, height)
        factor = max(0.1, float(scale or 2))
        image = image.resize(
            (
                max(1, int(image.width * factor)),
                max(1, int(image.height * factor)),
            ),
            Image.LANCZOS,
        )
        output = _save(image, path, "zoom")
        return f"Увеличенный фрагмент: {output}"

    @registry.tool(
        "screen_base64",
        "Вернуть снимок экрана в base64.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": [],
        },
        category="screen",
    )
    def screen_base64(x=None, y=None, width=None, height=None):
        image = _grab(x, y, width, height)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return encoded[:200] + "... (полный размер " + str(len(encoded)) + " символов)"
