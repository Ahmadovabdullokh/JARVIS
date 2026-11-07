import re
import sys
from difflib import SequenceMatcher


def configure_console():
    """Не даёт кириллице и спецсимволам ломать вывод в Windows."""

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        stream = kwargs.get("file") or sys.stdout
        text = " ".join(str(item) for item in args)
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(
            text.encode(encoding, "replace").decode(encoding, "replace")
            + "\n"
        )


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def contains_wake_word(text: str, wake_words: list[str]) -> bool:
    t = normalize_text(text)

    # Быстрые “грубые” совпадения по подстроке
    for w in wake_words:
        w_norm = normalize_text(w)
        if w_norm in t:
            return True

    # Если подстроки нет — пробуем “похожесть”
    # сравним wake_word с каждым словом в распознанной фразе
    words = t.split(" ")
    for w in wake_words:
        w_norm = normalize_text(w)
        for x in words:
            if similarity(w_norm, x) >= 0.65:
                return True

    # Дополнительно: “джарвис” часто слышат как “джар…”/“дарвис…”
    if "джар" in t and ("вис" in t or "висе" in t or "вес" in t):
        return True

    return False

def strip_wake_word(text: str, wake_words: list[str]) -> str:
    t = text.strip()

    # убираем то, что хоть как-то похоже на wake word
    t_norm = normalize_text(t)
    for w in wake_words:
        # убираем подстроку, если она есть
        t = re.sub(re.escape(w), "", t, flags=re.IGNORECASE)

    # чистим пробелы/пунктуацию слева
    t = t.strip()
    t = re.sub(r"^[,:;\-\s]+", "", t).strip()

    # если распознанный текст был типа "я лишь ...", а wake word не убрался,
    # просто вернём исходное (это лучше, чем пустить запрос мимо)
    if normalize_text(t) == t_norm:
        return text.strip()

    return t
