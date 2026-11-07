import shutil
from pathlib import Path

from app.doctor import format_report, run_checks
from app.observability import tracer
from app.rag import RagIndex
from app.sessions import store
from app.tools.common import BASE_DIR, resolve_path
from app.undo import journal

_RAG = None


def _rag():
    global _RAG
    if _RAG is None:
        _RAG = RagIndex()
    return _RAG


def register(registry):

    @registry.tool(
        "undo_last",
        "Отменить последнее изменение файлов.",
        {"type": "object", "properties": {}, "required": []},
        category="agent",
        danger="confirm",
    )
    def undo_last():
        return journal().undo_last()

    @registry.tool(
        "undo_list",
        "Показать последние операции, доступные для отмены.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="agent",
    )
    def undo_list(limit=20):
        return journal().summary(limit=limit)

    @registry.tool(
        "undo_clear",
        "Очистить журнал отмены и резервные копии.",
        {"type": "object", "properties": {}, "required": []},
        category="agent",
        danger="dangerous",
    )
    def undo_clear():
        return journal().clear()

    @registry.tool(
        "trace_tail",
        "Показать последние записи трассировки запросов.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="agent",
    )
    def trace_tail(limit=40):
        return tracer().tail(limit=limit)

    @registry.tool(
        "trace_clear",
        "Очистить журнал трассировки.",
        {"type": "object", "properties": {}, "required": []},
        category="agent",
        danger="confirm",
    )
    def trace_clear():
        return tracer().clear()

    @registry.tool(
        "doctor_check",
        "Проверить зависимости, ключи, OCR, ffmpeg и Playwright.",
        {"type": "object", "properties": {}, "required": []},
        category="agent",
    )
    def doctor_check():
        return format_report(run_checks())

    @registry.tool(
        "audit_export",
        "Скопировать журнал аудита в указанный файл.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="agent",
    )
    def audit_export(path):
        agent = getattr(registry.context, "agent", None)
        safety = getattr(agent, "safety", None)
        source = Path(
            getattr(safety, "audit_path", BASE_DIR / "data" / "audit.log")
        )
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        journal().record_write(target)
        if source.exists():
            shutil.copy2(source, target)
            return f"Аудит экспортирован: {target}"
        return "Журнал аудита пуст."

    @registry.tool(
        "rag_index",
        "Проиндексировать папку с текстовыми и офисными файлами.",
        {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "limit_files": {"type": "integer"},
            },
            "required": ["root"],
        },
        category="knowledge",
    )
    def rag_index(root, limit_files=2000):
        return _rag().index(
            resolve_path(root, must_exist=True),
            limit_files=limit_files,
        )

    @registry.tool(
        "rag_search",
        "Найти релевантные фрагменты в локальном индексе.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="knowledge",
    )
    def rag_search(query, limit=5):
        results = _rag().search(query, limit=limit)
        if not results:
            return "Ничего не найдено. Сначала выполните rag_index."
        lines = []
        for item in results:
            lines.append(
                f"{item['source']} (score {item['score']}):\n"
                f"{item['text']}"
            )
        return "\n\n".join(lines)

    @registry.tool(
        "rag_stats",
        "Показать статистику локального индекса.",
        {"type": "object", "properties": {}, "required": []},
        category="knowledge",
    )
    def rag_stats():
        stats = _rag().stats()
        return (
            f"Файлов: {stats['files']}\n"
            f"Фрагментов: {stats['chunks']}\n"
            f"Корней: {stats['roots']}\n"
            f"База: {stats['path']}"
        )

    @registry.tool(
        "rag_clear",
        "Очистить локальный индекс RAG.",
        {"type": "object", "properties": {}, "required": []},
        category="knowledge",
        danger="confirm",
    )
    def rag_clear():
        return _rag().clear()

    @registry.tool(
        "session_search",
        "Найти сообщения в сохранённых диалогах.",
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
    def session_search(query, limit=20):
        results = store().search(query, limit=limit)
        if not results:
            return "Ничего не найдено."
        return "\n".join(
            f"{item['created']} [{item['role']}] {item['content'][:300]}"
            for item in results
        )

    @registry.tool(
        "session_list",
        "Показать сохранённые сессии.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="memory",
    )
    def session_list(limit=20):
        items = store().sessions(limit=limit)
        if not items:
            return "Сохранённых сессий нет."
        return "\n".join(
            f"{item['id']} | {item['updated']} | {item['title']}"
            for item in items
        )

    @registry.tool(
        "session_clear",
        "Очистить историю текущей или всех сессий.",
        {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": [],
        },
        category="memory",
        danger="confirm",
    )
    def session_clear(session_id=None):
        return store().clear(session_id=session_id)
