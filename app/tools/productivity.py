import json
import random
import re
import threading
import time
from datetime import datetime, timedelta

from app.tools.common import BASE_DIR, optional_import, resolve_path
from app.undo import journal

DATA_DIR = BASE_DIR / "data"


def _load(name, default):
    path = DATA_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    journal().record_write(path)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def register(registry):

    @registry.tool(
        "notes_add",
        "Добавить заметку.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "tags": {"type": "array"},
            },
            "required": ["text"],
        },
        category="productivity",
    )
    def notes_add(text, tags=None):
        notes = _load("notes.json", [])
        notes.append(
            {
                "id": int(time.time() * 1000),
                "text": str(text),
                "tags": [str(item) for item in (tags or [])],
                "created": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _save("notes.json", notes)
        return f"Заметка добавлена. Всего заметок: {len(notes)}."

    @registry.tool(
        "notes_list",
        "Показать заметки.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="productivity",
    )
    def notes_list(query=None, limit=50):
        notes = _load("notes.json", [])
        if query:
            needle = str(query).lower()
            notes = [
                note
                for note in notes
                if needle in note.get("text", "").lower()
                or any(needle in tag.lower() for tag in note.get("tags", []))
            ]
        if not notes:
            return "Заметок нет."
        lines = []
        for note in notes[-int(limit or 50) :]:
            tags = ", ".join(note.get("tags", []))
            lines.append(
                f"#{note.get('id')} [{note.get('created')}] "
                f"{note.get('text')}" + (f" ({tags})" if tags else "")
            )
        return "\n".join(lines)

    @registry.tool(
        "notes_delete",
        "Удалить заметку по ID.",
        {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        category="productivity",
        danger="confirm",
    )
    def notes_delete(id):
        notes = _load("notes.json", [])
        remaining = [note for note in notes if note.get("id") != int(id)]
        _save("notes.json", remaining)
        return (
            "Заметка удалена."
            if len(remaining) < len(notes)
            else "Заметка не найдена."
        )

    @registry.tool(
        "todo_add",
        "Добавить задачу в список дел.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                },
                "due": {"type": "string"},
            },
            "required": ["text"],
        },
        category="productivity",
    )
    def todo_add(text, priority="normal", due=None):
        todos = _load("todos.json", [])
        todos.append(
            {
                "id": int(time.time() * 1000),
                "text": str(text),
                "priority": str(priority or "normal"),
                "due": due,
                "done": False,
                "created": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _save("todos.json", todos)
        return f"Задача добавлена. Активных: {sum(1 for item in todos if not item.get('done'))}."

    @registry.tool(
        "todo_list",
        "Показать список дел.",
        {
            "type": "object",
            "properties": {"all": {"type": "boolean"}},
            "required": [],
        },
        category="productivity",
    )
    def todo_list(all=False):
        todos = _load("todos.json", [])
        if not all:
            todos = [item for item in todos if not item.get("done")]
        if not todos:
            return "Список дел пуст."
        order = {"high": 0, "normal": 1, "low": 2}
        todos.sort(key=lambda item: order.get(item.get("priority"), 1))
        lines = []
        for item in todos:
            mark = "[x]" if item.get("done") else "[ ]"
            due = f" до {item['due']}" if item.get("due") else ""
            lines.append(
                f"{mark} #{item.get('id')} ({item.get('priority')}) "
                f"{item.get('text')}{due}"
            )
        return "\n".join(lines)

    @registry.tool(
        "todo_done",
        "Отметить задачу выполненной.",
        {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        category="productivity",
    )
    def todo_done(id):
        todos = _load("todos.json", [])
        for item in todos:
            if item.get("id") == int(id):
                item["done"] = True
                _save("todos.json", todos)
                return f"Задача #{id} выполнена."
        return "Задача не найдена."

    @registry.tool(
        "todo_delete",
        "Удалить задачу.",
        {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        category="productivity",
        danger="confirm",
    )
    def todo_delete(id):
        todos = _load("todos.json", [])
        remaining = [item for item in todos if item.get("id") != int(id)]
        _save("todos.json", remaining)
        return "Задача удалена." if len(remaining) < len(todos) else "Задача не найдена."

    @registry.tool(
        "reminder_add",
        "Добавить напоминание на время.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "when": {"type": "string"},
                "minutes": {"type": "integer"},
            },
            "required": ["text"],
        },
        category="productivity",
    )
    def reminder_add(text, when=None, minutes=None):
        reminders = _load("reminders.json", [])
        if minutes:
            target = datetime.now() + timedelta(minutes=int(minutes))
        elif when:
            try:
                target = datetime.fromisoformat(str(when))
            except ValueError:
                return "Формат времени: YYYY-MM-DDTHH:MM."
        else:
            return "Укажите when или minutes."
        reminders.append(
            {
                "id": int(time.time() * 1000),
                "text": str(text),
                "when": target.isoformat(timespec="seconds"),
                "done": False,
            }
        )
        _save("reminders.json", reminders)
        return f"Напоминание на {target:%d.%m.%Y %H:%M} добавлено."

    @registry.tool(
        "reminder_list",
        "Показать напоминания.",
        {"type": "object", "properties": {}, "required": []},
        category="productivity",
    )
    def reminder_list():
        reminders = _load("reminders.json", [])
        if not reminders:
            return "Напоминаний нет."
        lines = []
        for item in reminders:
            mark = "[x]" if item.get("done") else "[ ]"
            lines.append(
                f"{mark} #{item.get('id')} {item.get('when')} {item.get('text')}"
            )
        return "\n".join(lines)

    @registry.tool(
        "timer_start",
        "Запустить таймер с уведомлением.",
        {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": ["seconds"],
        },
        category="productivity",
    )
    def timer_start(seconds, label="Таймер"):
        delay = max(1, int(seconds or 1))

        def worker():
            time.sleep(delay)
            from app.tools.common import notify

            notify("JARVIS", f"{label}: время вышло.")

        threading.Thread(target=worker, daemon=True).start()
        return f"Таймер «{label}» на {delay} c запущен."

    @registry.tool(
        "pomodoro_start",
        "Запустить помодоро-таймер.",
        {
            "type": "object",
            "properties": {
                "work": {"type": "integer"},
                "break_time": {"type": "integer"},
            },
            "required": [],
        },
        category="productivity",
    )
    def pomodoro_start(work=25, break_time=5):
        work_seconds = max(1, int(work or 25) * 60)
        break_seconds = max(1, int(break_time or 5) * 60)

        def worker():
            from app.tools.common import notify

            time.sleep(work_seconds)
            notify("JARVIS", "Помодоро: время перерыва.")
            time.sleep(break_seconds)
            notify("JARVIS", "Помодоро завершён. Можно продолжать.")

        threading.Thread(target=worker, daemon=True).start()
        return f"Помодоро: {work} мин работы, {break_time} мин перерыва."

    @registry.tool(
        "text_word_count",
        "Подсчитать слова, символы и предложения.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": [],
        },
        category="productivity",
    )
    def text_word_count(text=None, path=None):
        if path:
            from app.tools.common import resolve_path

            text = resolve_path(path, must_exist=True).read_text(
                encoding="utf-8", errors="replace"
            )
        value = str(text or "")
        words = re.findall(r"\w+", value)
        sentences = [item for item in re.split(r"[.!?]+", value) if item.strip()]
        return (
            f"Символов: {len(value)}\n"
            f"Слов: {len(words)}\n"
            f"Предложений: {len(sentences)}\n"
            f"Абзацев: {len([item for item in value.splitlines() if item.strip()])}"
        )

    @registry.tool(
        "text_summarize",
        "Сделать краткое изложение текста.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "sentences": {"type": "integer"},
            },
            "required": ["text"],
        },
        category="productivity",
    )
    def text_summarize(text, sentences=5):
        parts = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", str(text))
            if item.strip()
        ]
        if len(parts) <= int(sentences or 5):
            return "\n".join(parts)
        words = re.findall(r"\w+", str(text).lower())
        frequency = {}
        for word in words:
            if len(word) > 3:
                frequency[word] = frequency.get(word, 0) + 1
        scored = []
        for index, sentence in enumerate(parts):
            score = sum(
                frequency.get(word, 0)
                for word in re.findall(r"\w+", sentence.lower())
            )
            scored.append((score, index, sentence))
        top = sorted(scored, reverse=True)[: int(sentences or 5)]
        top.sort(key=lambda item: item[1])
        return "\n".join(item[2] for item in top)

    @registry.tool(
        "text_translate",
        "Перевести текст.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["text", "target"],
        },
        category="productivity",
    )
    def text_translate(text, target="ru", source="auto"):
        translator_module = optional_import("deep_translator")
        if translator_module is None:
            return "Для перевода установите deep-translator."
        try:
            translator = translator_module.GoogleTranslator(
                source=str(source or "auto"),
                target=str(target),
            )
            return translator.translate(str(text))
        except Exception as error:
            return f"Ошибка перевода: {error}"

    @registry.tool(
        "text_define",
        "Найти определение слова.",
        {
            "type": "object",
            "properties": {"word": {"type": "string"}},
            "required": ["word"],
        },
        category="productivity",
    )
    def text_define(word):
        import requests

        try:
            response = requests.get(
                "https://api.dictionaryapi.dev/api/v2/entries/en/"
                + str(word),
                timeout=15,
            )
            data = response.json()
            meanings = []
            for entry in data if isinstance(data, list) else []:
                for meaning in entry.get("meanings", []):
                    for definition in meaning.get("definitions", [])[:3]:
                        meanings.append(
                            f"{meaning.get('partOfSpeech')}: "
                            f"{definition.get('definition')}"
                        )
            return "\n".join(meanings[:10]) or "Определение не найдено."
        except Exception as error:
            return f"Не удалось найти определение: {error}"

    @registry.tool(
        "wikipedia_search",
        "Найти статьи в Википедии.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="productivity",
    )
    def wikipedia_search(query, language="ru", limit=5):
        wikipedia = optional_import("wikipedia")
        if wikipedia is None:
            return "Для Википедии установите wikipedia."
        try:
            wikipedia.set_lang(str(language or "ru"))
            results = wikipedia.search(
                str(query), results=int(limit or 5)
            )
            return "\n".join(results) or "Статьи не найдены."
        except Exception as error:
            return f"Ошибка Википедии: {error}"

    @registry.tool(
        "wikipedia_summary",
        "Краткое содержание статьи Википедии.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "sentences": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="productivity",
    )
    def wikipedia_summary(query, language="ru", sentences=5):
        wikipedia = optional_import("wikipedia")
        if wikipedia is None:
            return "Для Википедии установите wikipedia."
        try:
            wikipedia.set_lang(str(language or "ru"))
            return wikipedia.summary(
                str(query), sentences=int(sentences or 5), auto_suggest=True
            )
        except Exception as error:
            return f"Ошибка Википедии: {error}"

    @registry.tool(
        "unit_convert",
        "Конвертировать единицы измерения.",
        {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from": {"type": "string"},
                "to": {"type": "string"},
            },
            "required": ["value", "from", "to"],
        },
        category="productivity",
    )
    def unit_convert(value, from_unit=None, to=None, **kwargs):
        from_unit = from_unit or kwargs.get("from")
        to_unit = to or kwargs.get("to")
        factors = {
            "km": 1000.0,
            "m": 1.0,
            "cm": 0.01,
            "mm": 0.001,
            "mile": 1609.344,
            "ft": 0.3048,
            "inch": 0.0254,
            "kg": 1.0,
            "g": 0.001,
            "lb": 0.45359237,
            "oz": 0.028349523125,
            "l": 1.0,
            "ml": 0.001,
            "gallon": 3.785411784,
        }
        if from_unit in factors and to_unit in factors:
            return (
                f"{value} {from_unit} = "
                f"{float(value) * factors[from_unit] / factors[to_unit]:.6g} {to_unit}"
            )
        if from_unit in ("c", "celsius") and to_unit in ("f", "fahrenheit"):
            return f"{float(value) * 9 / 5 + 32:.2f} °F"
        if from_unit in ("f", "fahrenheit") and to_unit in ("c", "celsius"):
            return f"{(float(value) - 32) * 5 / 9:.2f} °C"
        return "Неизвестные единицы."

    @registry.tool(
        "currency_convert",
        "Конвертировать валюту по курсу.",
        {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "from": {"type": "string"},
                "to": {"type": "string"},
            },
            "required": ["amount", "from", "to"],
        },
        category="productivity",
    )
    def currency_convert(amount, from_currency=None, to=None, **kwargs):
        from_currency = from_currency or kwargs.get("from")
        to_currency = to or kwargs.get("to")
        import requests

        try:
            response = requests.get(
                f"https://api.frankfurter.app/latest?amount={amount}"
                f"&from={from_currency}&to={to_currency}",
                timeout=15,
            )
            data = response.json()
            value = data.get("rates", {}).get(str(to_currency).upper())
            if value is None:
                return f"Нет курса {from_currency} -> {to_currency}."
            return f"{amount} {from_currency} = {value} {to_currency}"
        except Exception as error:
            return f"Ошибка курса валют: {error}"

    @registry.tool(
        "date_calculate",
        "Разница дат или прибавление дней.",
        {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": [],
        },
        category="productivity",
    )
    def date_calculate(start=None, end=None, days=None):
        try:
            start_date = (
                datetime.fromisoformat(str(start))
                if start
                else datetime.now()
            )
            if days is not None:
                return (
                    start_date + timedelta(days=int(days))
                ).strftime("%Y-%m-%d %H:%M")
            end_date = (
                datetime.fromisoformat(str(end)) if end else datetime.now()
            )
            delta = end_date - start_date
            return (
                f"Дней: {delta.days}, секунд: {int(delta.total_seconds())}"
            )
        except ValueError as error:
            return f"Ошибка даты: {error}"

    @registry.tool(
        "random_choice",
        "Выбрать случайный вариант.",
        {
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        },
        category="productivity",
    )
    def random_choice(items):
        if not items:
            return "Список пуст."
        return str(random.choice(items))

    @registry.tool(
        "random_dice",
        "Бросить кубики.",
        {
            "type": "object",
            "properties": {
                "sides": {"type": "integer"},
                "count": {"type": "integer"},
            },
            "required": [],
        },
        category="productivity",
    )
    def random_dice(sides=6, count=1):
        sides = max(2, int(sides or 6))
        rolls = [
            random.randint(1, sides) for _ in range(max(1, int(count or 1)))
        ]
        return f"Результат: {rolls} (сумма {sum(rolls)})"

    @registry.tool(
        "random_coin",
        "Подбросить монету.",
        {"type": "object", "properties": {}, "required": []},
        category="productivity",
    )
    def random_coin():
        return random.choice(["Орёл", "Решка"])

    @registry.tool(
        "contacts_add",
        "Добавить контакт в локальную книгу.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
                "kind": {"type": "string"},
            },
            "required": ["name", "value"],
        },
        category="productivity",
    )
    def contacts_add(name, value, kind="phone"):
        contacts = _load("contacts.json", [])
        if not isinstance(contacts, list):
            contacts = []
        contacts.append(
            {
                "name": str(name or "").strip(),
                "value": str(value or "").strip(),
                "kind": str(kind or "phone").strip(),
            }
        )
        _save("contacts.json", contacts)
        return f"Контакт сохранён: {name}"

    @registry.tool(
        "contacts_search",
        "Найти контакт по имени, телефону или email.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        category="productivity",
    )
    def contacts_search(query):
        needle = str(query or "").strip().lower()
        contacts = _load("contacts.json", [])
        if not isinstance(contacts, list):
            contacts = []
        matches = [
            item
            for item in contacts
            if needle in str(item.get("name", "")).lower()
            or needle in str(item.get("value", "")).lower()
        ]
        if not matches:
            return "Контакты не найдены."
        return "\n".join(
            f"{item.get('name')} | {item.get('kind')}: {item.get('value')}"
            for item in matches
        )

    @registry.tool(
        "calendar_read_ics",
        "Показать события из ICS-календаря.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="productivity",
    )
    def calendar_read_ics(path, days=30):
        icalendar = optional_import("icalendar")
        if icalendar is None:
            return "Для работы с ICS установите icalendar."
        source = resolve_path(path, must_exist=True)
        calendar = icalendar.Calendar.from_ical(
            source.read_bytes()
        )
        now = datetime.now()
        deadline = now + timedelta(days=max(1, int(days or 30)))
        events = []
        for component in calendar.walk("VEVENT"):
            start = component.get("DTSTART")
            if start is None:
                continue
            value = start.dt
            if isinstance(value, datetime):
                when = value.replace(tzinfo=None)
            else:
                when = datetime.combine(value, datetime.min.time())
            if now <= when <= deadline:
                events.append(
                    f"{when.strftime('%Y-%m-%d %H:%M')} | "
                    f"{component.get('SUMMARY', 'Без названия')}"
                )
        events.sort()
        return "\n".join(events) or "Событий не найдено."

    @registry.tool(
        "calendar_create_ics",
        "Создать ICS-файл с одним событием.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["path", "title", "start"],
        },
        category="productivity",
    )
    def calendar_create_ics(
        path,
        title,
        start,
        end=None,
        description="",
    ):
        icalendar = optional_import("icalendar")
        if icalendar is None:
            return "Для работы с ICS установите icalendar."
        try:
            start_dt = datetime.fromisoformat(str(start))
            end_dt = (
                datetime.fromisoformat(str(end))
                if end
                else start_dt + timedelta(hours=1)
            )
        except ValueError as error:
            return f"Ошибка даты: {error}"

        calendar = icalendar.Calendar()
        calendar.add("prodid", "-//JARVIS//RU")
        calendar.add("version", "2.0")
        event = icalendar.Event()
        event.add("summary", str(title))
        event.add("dtstart", start_dt)
        event.add("dtend", end_dt)
        if description:
            event.add("description", str(description))
        calendar.add_component(event)

        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(target)
        target.write_bytes(calendar.to_ical())
        return f"Событие создано: {target}"
