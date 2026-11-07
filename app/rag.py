import math
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

from app.paths import BASE_DIR
from app.tools.common import optional_import

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".json", ".csv", ".log",
    ".html", ".htm", ".ini", ".yaml", ".yml", ".toml", ".xml",
    ".pdf", ".docx", ".pptx", ".xlsx",
}

STOPWORDS = {
    "а", "без", "бы", "в", "во", "для", "до", "его", "ее", "если",
    "есть", "же", "за", "и", "из", "или", "как", "ко", "к", "ли", "мне",
    "мы", "на", "над", "не", "ни", "но", "ну", "о", "об", "от", "по",
    "под", "при", "с", "со", "так", "то", "у", "что", "это", "я",
    "the", "a", "an", "and", "for", "in", "is", "of", "on", "or", "to",
}


def _terms(text):
    words = re.findall(r"[\w\-]+", str(text or "").lower().replace("ё", "е"))
    return [
        word
        for word in words
        if len(word) >= 3 and word not in STOPWORDS
    ]


class RagIndex:

    def __init__(self, path=None):
        self.path = (
            Path(path)
            if path
            else BASE_DIR / "data" / "rag.db"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root TEXT NOT NULL,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_root
                    ON chunks(root);
                """
            )
            self._connection.commit()

    def _iter_files(self, root, limit_files=2000):
        count = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path
            count += 1
            if count >= max(1, int(limit_files or 2000)):
                return

    def _read_text(self, path):
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pypdf = optional_import("pypdf")
            if pypdf is None:
                return ""
            reader = pypdf.PdfReader(str(path))
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        if suffix == ".docx":
            docx = optional_import("docx")
            if docx is None:
                return ""
            document = docx.Document(str(path))
            return "\n".join(
                paragraph.text for paragraph in document.paragraphs
            )
        if suffix == ".pptx":
            pptx = optional_import("pptx")
            if pptx is None:
                return ""
            presentation = pptx.Presentation(str(path))
            lines = []
            for slide in presentation.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        lines.append(shape.text)
            return "\n".join(lines)
        if suffix == ".xlsx":
            openpyxl = optional_import("openpyxl")
            if openpyxl is None:
                return ""
            workbook = openpyxl.load_workbook(
                str(path),
                read_only=True,
                data_only=True,
            )
            lines = []
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    lines.append(
                        " ".join(
                            str(cell)
                            for cell in row
                            if cell is not None
                        )
                    )
            workbook.close()
            return "\n".join(lines)
        return path.read_text(encoding="utf-8", errors="ignore")

    def _chunks(self, text, size=900, overlap=150):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def index(self, root, limit_files=2000):
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            return f"Папка не найдена: {root_path}"
        if not root_path.is_dir():
            return f"Это не папка: {root_path}"

        files = 0
        chunks = 0
        errors = 0
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        root_key = str(root_path)
        with self._lock:
            self._connection.execute(
                "DELETE FROM chunks WHERE root = ?",
                (root_key,),
            )
            for path in self._iter_files(root_path, limit_files):
                try:
                    text = self._read_text(path)
                except Exception:
                    errors += 1
                    continue
                if not text.strip():
                    continue
                files += 1
                for chunk in self._chunks(text):
                    self._connection.execute(
                        "INSERT INTO chunks "
                        "(root, source, text, created) VALUES (?, ?, ?, ?)",
                        (root_key, str(path), chunk, now),
                    )
                    chunks += 1
            self._connection.commit()
        return (
            f"Проиндексировано файлов: {files}, фрагментов: {chunks}, "
            f"ошибок: {errors}. Корень: {root_path}"
        )

    def search(self, query, limit=5):
        terms = _terms(query)
        if not terms:
            return []
        with self._lock:
            rows = self._connection.execute(
                "SELECT source, text FROM chunks LIMIT 5000"
            ).fetchall()
        if not rows:
            return []

        documents = []
        for row in rows:
            tokens = _terms(row["text"])
            if tokens:
                documents.append((row["source"], row["text"], tokens))

        document_frequency = Counter()
        for _, _, tokens in documents:
            for term in set(tokens):
                document_frequency[term] += 1

        total = len(documents)
        scored = []
        for source, text, tokens in documents:
            counts = Counter(tokens)
            score = 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                idf = math.log(
                    (total + 1) / (document_frequency[term] + 0.5)
                ) + 1.0
                score += (frequency / (frequency + 1.5)) * idf
            if score > 0:
                scored.append((score, source, text))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"source": source, "text": text, "score": round(score, 3)}
            for score, source, text in scored[: max(1, int(limit or 5))]
        ]

    def stats(self):
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS chunks, "
                "COUNT(DISTINCT source) AS files, "
                "COUNT(DISTINCT root) AS roots FROM chunks"
            ).fetchone()
        return {
            "chunks": row["chunks"] if row else 0,
            "files": row["files"] if row else 0,
            "roots": row["roots"] if row else 0,
            "path": str(self.path),
        }

    def clear(self):
        with self._lock:
            self._connection.execute("DELETE FROM chunks")
            self._connection.commit()
        return "Индекс RAG очищен."

    def close(self):
        with self._lock:
            self._connection.close()
