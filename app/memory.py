import json
import re
import threading
from pathlib import Path

from app.paths import DATA_DIR

DEFAULT_PATH = DATA_DIR / "memory.json"

_STOPWORDS = {
    "а", "без", "бы", "в", "во", "для", "до", "его", "ее", "если",
    "есть", "же", "за", "и", "из", "или", "как", "ко", "к", "ли", "мне",
    "мы", "на", "над", "не", "ни", "но", "ну", "о", "об", "от", "по",
    "под", "при", "с", "со", "так", "то", "у", "что", "это", "я",
    "the", "a", "an", "and", "for", "in", "is", "of", "on", "or", "to",
}


def _terms(text):
    words = re.findall(
        r"[\w\-]+",
        str(text or "").lower().replace("ё", "е"),
    )
    return [
        word
        for word in words
        if len(word) >= 3 and word not in _STOPWORDS
    ]


def _score(terms, text):
    haystack = str(text or "").lower().replace("ё", "е")
    score = 0
    for term in terms:
        if term in haystack:
            score += 2
        elif len(term) >= 4 and term[:4] in haystack:
            score += 1
    return score


class Memory:

    def __init__(self, path=None, max_facts=50):
        self.path = Path(path) if path else DEFAULT_PATH
        self.max_facts = max(1, int(max_facts or 50))
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        if not self.path.exists():
            return {"facts": [], "profile": {}}

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {"facts": [], "profile": {}}

        if not isinstance(data, dict):
            return {"facts": [], "profile": {}}

        facts = data.get("facts")
        profile = data.get("profile")

        return {
            "facts": [
                str(fact).strip()
                for fact in facts
                if str(fact).strip()
            ] if isinstance(facts, list) else [],
            "profile": profile if isinstance(profile, dict) else {},
        }

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(
                self._data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temp_path.replace(self.path)

    def remember(self, fact):
        fact = str(fact or "").strip()
        if not fact:
            return False

        with self._lock:
            existing = {
                item.casefold()
                for item in self._data["facts"]
            }

            if fact.casefold() in existing:
                return False

            self._data["facts"].append(fact)
            self._data["facts"] = self._data["facts"][
                -self.max_facts:
            ]
            self._save()

        return True

    def forget_all(self):
        with self._lock:
            self._data = {"facts": [], "profile": {}}
            self._save()

    def set_profile(self, key, value):
        key = str(key or "").strip()
        if not key:
            return False

        with self._lock:
            self._data["profile"][key] = str(value or "").strip()
            self._save()

        return True

    def facts(self):
        with self._lock:
            return list(self._data["facts"])

    def profile(self):
        with self._lock:
            return dict(self._data["profile"])

    def search(self, query, limit=10):
        terms = _terms(query)
        if not terms:
            return []
        with self._lock:
            facts = list(self._data["facts"])
            profile = dict(self._data["profile"])

        scored = []
        for key, value in profile.items():
            text = f"{key}: {value}"
            score = _score(terms, text)
            if score:
                scored.append((score, text))
        for fact in facts:
            score = _score(terms, fact)
            if score:
                scored.append((score, fact))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            text for _, text in scored[: max(1, int(limit or 10))]
        ]

    def summary(self):
        with self._lock:
            facts = list(self._data["facts"])
            profile = dict(self._data["profile"])

        lines = []

        for key, value in profile.items():
            if value:
                lines.append(f"{key}: {value}.")

        for fact in facts:
            lines.append(f"- {fact}.")

        if not lines:
            return ""

        return "Сведения о пользователе и прошлых запросах:\n" + "\n".join(
            lines
        )
