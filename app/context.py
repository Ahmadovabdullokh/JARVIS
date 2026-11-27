"""Сборка «умного контекста» для системного промпта.

Объединяет три дешёвых источника (без локальных моделей и эмбеддингов):

* факты и профиль из ``Memory``;
* релевантные прошлые сообщения из ``SessionStore`` (FTS5);
* связанные локальные документы из ``RagIndex`` (FTS5).

Каждый источник опционален и обёрнут в try/except: сбой поиска не должен
ломать ответ. Результат — короткий текстовый блок, который дописывается к
системному промпту.
"""

from typing import Any, Optional

from app.logging import get_logger

log = get_logger(__name__)


class ContextBuilder:

    def __init__(self, memory=None, sessions=None, rag=None):
        self.memory = memory
        self.sessions = sessions
        self.rag = rag

    def _memory_block(self, query, limit) -> str:
        if self.memory is None:
            return ""
        try:
            facts = self.memory.search(query, limit=limit)
        except Exception as error:
            log.info("[CONTEXT] memory: %s", error)
            return ""
        facts = [str(item).strip() for item in facts if str(item).strip()]
        if not facts:
            return ""
        return "Память и предпочтения:\n" + "\n".join(
            f"- {fact}" for fact in facts
        )

    def _sessions_block(self, query, limit) -> str:
        if self.sessions is None:
            return ""
        try:
            hits = self.sessions.search(query, limit=limit)
        except Exception as error:
            log.info("[CONTEXT] sessions: %s", error)
            return ""
        lines = []
        for hit in hits:
            content = str(hit.get("content", "")).strip()
            if not content:
                continue
            role = str(hit.get("role", "")).strip() or "?"
            content = " ".join(content.split())
            lines.append(f"- [{role}] {content[:240]}")
        if not lines:
            return ""
        return "Из прошлых разговоров:\n" + "\n".join(lines)

    def _rag_block(self, query, limit) -> str:
        if self.rag is None:
            return ""
        try:
            hits = self.rag.search(query, limit=limit)
        except Exception as error:
            log.info("[CONTEXT] rag: %s", error)
            return ""
        lines = []
        for hit in hits:
            text = str(hit.get("text", "")).strip()
            if not text:
                continue
            source = str(hit.get("source", "")).strip()
            text = " ".join(text.split())
            prefix = f"{source}: " if source else ""
            lines.append(f"- {prefix}{text[:300]}")
        if not lines:
            return ""
        return "Связанные локальные документы:\n" + "\n".join(lines)

    def build(
        self,
        query: str,
        memory_limit: int = 6,
        session_limit: int = 4,
        rag_limit: int = 3,
        max_chars: int = 2400,
    ) -> str:
        query = str(query or "").strip()
        if not query:
            return ""
        blocks = [
            self._memory_block(query, memory_limit),
            self._sessions_block(query, session_limit),
            self._rag_block(query, rag_limit),
        ]
        parts = [block for block in blocks if block]
        if not parts:
            return ""
        text = "\n\n".join(parts).strip()
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        return text


def build_context(
    query: str,
    memory: Any = None,
    sessions: Optional[Any] = None,
    rag: Any = None,
    **kwargs,
) -> str:
    return ContextBuilder(
        memory=memory,
        sessions=sessions,
        rag=rag,
    ).build(query, **kwargs)
