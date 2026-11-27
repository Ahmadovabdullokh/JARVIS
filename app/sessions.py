import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from app.paths import DATA_DIR


def _fts_query(text):
    """Готовит безопасный FTS5-запрос из пользовательской строки."""
    terms = re.findall(r"[\w\-]+", str(text or "").lower())
    quoted = [f'"{term}"' for term in terms if len(term) >= 2]
    return " OR ".join(quoted[:24])


class SessionStore:

    def __init__(self, path=None):
        self.path = (
            Path(path)
            if path
            else DATA_DIR / "sessions.db"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        # WAL + NORMAL: заметно быстрее записи при слабом диске,
        # безопасно для однопроцессного приложения.
        try:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        self._fts = False
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}',
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_messages_created
                    ON messages(created);
                """
            )
            self._connection.commit()
        self._init_fts()

    def _init_fts(self):
        """Полнотекстовый индекс FTS5 (быстрый поиск по истории).

        FTS5 встроен в sqlite3 и не требует зависимостей/памяти.
        Если сборка Python без FTS5 — молча остаёмся на fallback.
        """

        try:
            self._connection.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    content='messages',
                    content_rowid='id',
                    tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS messages_ai
                    AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content)
                    VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS messages_ad
                    AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS messages_au
                    AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO messages_fts(rowid, content)
                    VALUES (new.id, new.content);
                END;
                """
            )
            self._connection.commit()
            self._fts = True
        except sqlite3.DatabaseError:
            self._fts = False
            return
        # Первичная индексация уже существующих сообщений.
        try:
            indexed = self._connection.execute(
                "SELECT COUNT(*) FROM messages_fts"
            ).fetchone()[0]
            existing = self._connection.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]
            if indexed == 0 and existing > 0:
                self._connection.execute(
                    "INSERT INTO messages_fts(messages_fts) "
                    "VALUES ('rebuild')"
                )
                self._connection.commit()
        except sqlite3.DatabaseError:
            self._fts = False

    def _now(self):
        return time.strftime("%Y-%m-%dT%H:%M:%S")

    def create_session(self, title="JARVIS"):
        session_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock:
            self._connection.execute(
                "INSERT INTO sessions (id, title, created, updated) "
                "VALUES (?, ?, ?, ?)",
                (session_id, str(title or "JARVIS"), now, now),
            )
            self._connection.commit()
        return session_id

    def ensure_session(self, session_id=None, title="JARVIS"):
        session_id = str(session_id or "").strip()
        if session_id:
            now = self._now()
            with self._lock:
                row = self._connection.execute(
                    "SELECT id FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if row is not None:
                    return session_id
                self._connection.execute(
                    "INSERT INTO sessions (id, title, created, updated) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, str(title or "JARVIS"), now, now),
                )
                self._connection.commit()
            return session_id
        return self.create_session(title)

    def latest_session_id(self):
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM sessions ORDER BY updated DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def add_message(self, session_id, role, content, meta=None):
        session_id = self.ensure_session(session_id)
        now = self._now()
        with self._lock:
            self._connection.execute(
                "INSERT INTO messages "
                "(session_id, role, content, meta, created) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    str(role or "user"),
                    str(content or ""),
                    json.dumps(meta or {}, ensure_ascii=False, default=str),
                    now,
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated = ? WHERE id = ?",
                (now, session_id),
            )
            self._connection.commit()
        return session_id

    def messages(self, session_id, limit=20):
        with self._lock:
            rows = self._connection.execute(
                "SELECT role, content, meta, created FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (str(session_id), max(1, int(limit or 20))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def history(self, session_id, limit=20):
        return [
            {
                "role": row["role"],
                "content": row["content"],
            }
            for row in self.messages(session_id, limit=limit)
            if row["role"] in {"user", "assistant"}
        ]

    def search(self, query, limit=20):
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, int(limit or 20))

        if self._fts:
            fts_query = _fts_query(query)
            if fts_query:
                try:
                    with self._lock:
                        rows = self._connection.execute(
                            "SELECT m.session_id, m.role, m.content, "
                            "m.created, bm25(messages_fts) AS rank "
                            "FROM messages_fts "
                            "JOIN messages m ON m.id = messages_fts.rowid "
                            "WHERE messages_fts MATCH ? "
                            "ORDER BY rank LIMIT ?",
                            (fts_query, limit),
                        ).fetchall()
                    if rows:
                        return [
                            {
                                "session_id": row["session_id"],
                                "role": row["role"],
                                "content": row["content"],
                                "created": row["created"],
                            }
                            for row in rows
                        ]
                except sqlite3.DatabaseError:
                    pass

        # Fallback: подстрочный поиск по последним сообщениям.
        needle = query.casefold()
        with self._lock:
            rows = self._connection.execute(
                "SELECT session_id, role, content, created FROM messages "
                "ORDER BY id DESC LIMIT 1000"
            ).fetchall()
        matches = [
            dict(row)
            for row in rows
            if needle in str(row["content"]).casefold()
        ]
        return matches[:limit]

    def sessions(self, limit=20):
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, title, created, updated FROM sessions "
                "ORDER BY updated DESC LIMIT ?",
                (max(1, int(limit or 20)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear(self, session_id=None):
        with self._lock:
            if session_id:
                self._connection.execute(
                    "DELETE FROM messages WHERE session_id = ?",
                    (str(session_id),),
                )
            else:
                self._connection.execute("DELETE FROM messages")
            self._connection.commit()
        return "История очищена."

    def close(self):
        with self._lock:
            self._connection.close()


_STORE = None


def store():
    global _STORE
    if _STORE is None:
        _STORE = SessionStore()
    return _STORE
