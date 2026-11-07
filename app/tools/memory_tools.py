import json
import time
from pathlib import Path

from app.memory import DEFAULT_PATH, Memory
from app.tools.common import BASE_DIR, resolve_path


def _memory():
    return Memory(path=DEFAULT_PATH)


def register(registry):

    @registry.tool(
        "memory_remember",
        "Запомнить факт о пользователе или разговоре.",
        {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
        category="memory",
    )
    def memory_remember(fact):
        stored = _memory().remember(fact)
        return "Запомнено." if stored else "Этот факт уже есть в памяти."

    @registry.tool(
        "memory_facts",
        "Показать все сохранённые факты.",
        {"type": "object", "properties": {}, "required": []},
        category="memory",
    )
    def memory_facts():
        facts = _memory().facts()
        if not facts:
            return "Память пуста."
        return "\n".join(f"- {fact}" for fact in facts)

    @registry.tool(
        "memory_search",
        "Найти факты в памяти.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        category="memory",
    )
    def memory_search(query):
        matches = _memory().search(query)
        return (
            "\n".join(f"- {item}" for item in matches)
            or "Ничего не найдено."
        )

    @registry.tool(
        "memory_profile_set",
        "Сохранить параметр профиля пользователя.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
        category="memory",
    )
    def memory_profile_set(key, value):
        _memory().set_profile(key, value)
        return f"Профиль: {key} = {value}"

    @registry.tool(
        "memory_profile_get",
        "Прочитать профиль пользователя.",
        {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": [],
        },
        category="memory",
    )
    def memory_profile_get(key=None):
        data = _memory()
        if key:
            return data.summary() if not key else _profile_value(data, key)
        return data.summary() or "Профиль пуст."

    @registry.tool(
        "memory_summary",
        "Краткая сводка памяти.",
        {"type": "object", "properties": {}, "required": []},
        category="memory",
    )
    def memory_summary():
        return _memory().summary() or "Память пуста."

    @registry.tool(
        "memory_forget_all",
        "Очистить память полностью.",
        {"type": "object", "properties": {}, "required": []},
        category="memory",
        danger="dangerous",
    )
    def memory_forget_all():
        _memory().forget_all()
        return "Память очищена."

    @registry.tool(
        "memory_stats",
        "Статистика памяти.",
        {"type": "object", "properties": {}, "required": []},
        category="memory",
    )
    def memory_stats():
        data = _memory()
        path = Path(DEFAULT_PATH)
        size = path.stat().st_size if path.exists() else 0
        return (
            f"Фактов: {len(data.facts())}\n"
            f"Файл: {path}\n"
            f"Размер: {size} байт"
        )

    @registry.tool(
        "memory_export",
        "Экспортировать память в JSON-файл.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="memory",
    )
    def memory_export(path):
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(DEFAULT_PATH)
        if source.exists():
            target.write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            target.write_text(
                json.dumps({"facts": [], "profile": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
        return f"Память экспортирована: {target}"

    @registry.tool(
        "memory_import",
        "Импортировать память из JSON-файла.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="memory",
        danger="confirm",
    )
    def memory_import(path):
        source = resolve_path(path, must_exist=True)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception as error:
            return f"Не удалось прочитать файл: {error}"
        memory = _memory()
        for fact in data.get("facts", []):
            memory.remember(fact)
        for key, value in data.get("profile", {}).items():
            memory.set_profile(key, value)
        return "Память импортирована."

    @registry.tool(
        "conversation_log",
        "Записать заметку о разговоре.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "role": {"type": "string"},
            },
            "required": ["text"],
        },
        category="memory",
    )
    def conversation_log(text, role="assistant"):
        path = BASE_DIR / "data" / "conversations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "role": str(role or "assistant"),
            "text": str(text),
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return "Запись добавлена в журнал разговоров."

    @registry.tool(
        "conversation_search",
        "Найти записи в журнале разговоров.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="memory",
    )
    def conversation_search(query, limit=20):
        path = BASE_DIR / "data" / "conversations.jsonl"
        if not path.exists():
            return "Журнал разговоров пуст."
        needle = str(query).lower()
        matches = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if needle in line.lower():
                matches.append(line)
        return "\n".join(matches[-int(limit or 20) :]) or "Ничего не найдено."


def _profile_value(memory, key):
    path = Path(memory.path)
    if not path.exists():
        return "Профиль пуст."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "Профиль пуст."
    value = data.get("profile", {}).get(str(key))
    return str(value) if value is not None else f"Параметр «{key}» не найден."
