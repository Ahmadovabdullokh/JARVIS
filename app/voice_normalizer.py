import re
from difflib import SequenceMatcher

# Исправления отдельных слов
REPLACEMENTS = {
    # JARVIS
    "джарвес": "джарвис",
    "джарви": "джарвис",
    "джарвиз": "джарвис",
    "джарвиц": "джарвис",
    "дарвис": "джарвис",
    "дарвиз": "джарвис",
    "дарвиса": "джарвис",
    "дарвизу": "джарвис",
    "дарвисе": "джарвис",
    "равис": "джарвис",
    "равиз": "джарвис",
    "рависа": "джарвис",
    "равизу": "джарвис",
    "рависе": "джарвис",
    "арвис": "джарвис",
    "арвиз": "джарвис",
    "арвиса": "джарвис",
    "арвизу": "джарвис",
    "арвисе": "джарвис",
    "джавис": "джарвис",
    "джавиз": "джарвис",
    "жавис": "джарвис",
    "жавиз": "джарвис",
    "чавис": "джарвис",
    "чавиз": "джарвис",
    "джависа": "джарвис",
    "жависа": "джарвис",
    "javis": "jarvis",
    "jarves": "jarvis",
    "jarvus": "jarvis",
    "джарвиза": "джарвис",
    "джарвизу": "джарвис",
    "джарвизе": "джарвис",
    "жарвис": "джарвис",
    "жарвес": "джарвис",
    "жарвиса": "джарвис",
    "жарвиз": "джарвис",
    "чарвис": "джарвис",
    "джарвисс": "джарвис",
    "джарвиса": "джарвис",
    "джарвису": "джарвис",
    "джарвисе": "джарвис",

    # YouTube
    "ютюб": "ютуб",
    "ютьюб": "ютуб",
    "ю туб": "ютуб",
    "ютубб": "ютуб",
    "ютубеe": "ютубе",
    "ютубее": "ютубе",
    "вонту": "ютуб",
    "вонту б": "ютуб",

    # Browser
    "фраузер": "браузер",
    "браузерр": "браузер",

    # Apps
    "телеграмм": "телеграм",
    "блокнотт": "блокнот",
    "блок нот": "блокнот",
    "калькуляторр": "калькулятор",

    # Open
    "крой": "открой",
    "крои": "открой",
    "кройте": "открой",
    "открою": "открой",
    "откроем": "открой",
    "открываю": "открой",
    "открывай": "открой",
    "откройте": "открой",

    # Start
    "запущу": "запусти",
    "запускаю": "запусти",
    "запускай": "запусти",

    # Enable
    "включу": "включи",
    "включаю": "включи",
    "включай": "включи",

    # Close
    "закрою": "закрой",
    "закрываю": "закрой",
    "закрывай": "закрой",
    "закройте": "закрой",

    # Turn off
    "выключу": "выключи",
    "выключаю": "выключи",
    "выключай": "выключи",
}


PHRASE_REPLACEMENTS = {
    # Windows
    "свернинг с окна": "сверни все окна",
    "свернинг окна": "сверни все окна",
    "свернись окна": "сверни все окна",
    "сверни с окна": "сверни все окна",
    "сверни все окна": "сверни все окна",
    "сверни окна": "сверни все окна",
    "свернуть окна": "сверни все окна",
    "свернуть все окна": "сверни все окна",
    "и все окна": "сверни все окна",

    # Рабочий стол
    "покажи стол": "покажи рабочий стол",
    "покажи рабочий стол": "покажи рабочий стол",
    "рабочий стол": "покажи рабочий стол",

    # Окна
    "развернись окно": "разверни окно",
    "разверни открывшийся окно": "разверни окно",
    "разверни открытое окно": "разверни окно",
    "развернуть окно": "разверни окно",

    "закрой это окно": "закрой текущее окно",
    "закрой это": "закрой текущее окно",

    # YouTube
    "в ютуб": "на ютубе",
    "в ютюбе": "на ютубе",
    "в ютубе": "на ютубе",

    # Scroll
    "полистай вниз": "листай вниз",
    "пролистай вниз": "листай вниз",
    "прокрути вниз": "листай вниз",
    "листани вниз": "листай вниз",
    "листань вниз": "листай вниз",
    "покрути вниз": "листай вниз",

    "полистай вверх": "листай вверх",
    "пролистай вверх": "листай вверх",
    "прокрути вверх": "листай вверх",
    "листани вверх": "листай вверх",
    "листань вверх": "листай вверх",
    "покрути вверх": "листай вверх",

    # Video
    "подставь видео на паузу": "поставь видео на паузу",
    "поставь видео на паузе": "поставь видео на паузу",
    "поставь видио на паузу": "поставь видео на паузу",
    "поставь видео паузу": "поставь видео на паузу",

    # Fullscreen
    "разверни в видео на верх экран": "разверни видео на весь экран",
    "разверни видео на весь экран": "разверни видео на весь экран",
}


WAKE_WORDS = {
    "джарвис",
    "jarvis",
    "джарвиз",
    "дарвис",
}

WAKE_WORD_MARKERS = ("авис", "авиз", "рвис", "рвиз", "jarvis")
WAKE_WORD_STARTS = ("д", "р", "а", "ж", "ч", "j")


def _looks_like_jarvis(word: str) -> bool:
    if not 4 <= len(word) <= 9:
        return False

    if not any(marker in word for marker in WAKE_WORD_MARKERS):
        return False

    return word.startswith(WAKE_WORD_STARTS)


def _is_wake_word(word: str, wake_words=None) -> bool:
    word = str(word or "").casefold().strip()
    if not word:
        return False

    words = {
        str(item).casefold().strip()
        for item in (wake_words or WAKE_WORDS)
        if str(item).strip()
    }

    if word in words:
        return True

    if any(
        word.startswith(wake_word) and word != wake_word
        for wake_word in words
    ):
        return False

    jarvis_mode = any(
        wake_word in WAKE_WORDS
        for wake_word in words
    )

    if jarvis_mode and _looks_like_jarvis(word):
        return True

    return any(
        SequenceMatcher(None, word, wake_word).ratio() >= 0.85
        for wake_word in words
    )


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower().strip()

    text = re.sub(
        r"[^\w\s\-]",
        " ",
        text,
        flags=re.UNICODE
    )

    text = re.sub(r"\s+", " ", text).strip()

    # Сначала длинные фразы
    for wrong, correct in sorted(
        PHRASE_REPLACEMENTS.items(),
        key=lambda item: len(item[0]),
        reverse=True
    ):
        text = re.sub(
            rf"(?<!\w){re.escape(wrong)}(?!\w)",
            correct,
            text
        )

    # Отдельные слова
    for wrong, correct in sorted(
        REPLACEMENTS.items(),
        key=lambda item: len(item[0]),
        reverse=True
    ):
        text = re.sub(
            rf"(?<!\w){re.escape(wrong)}(?!\w)",
            correct,
            text
        )

    # Важное исправление YouTube:
    # "на ютуб" -> "на ютубе"
    # но "на ютубе" повторно НЕ изменяется.
    text = re.sub(
        r"\bна\s+ютуб(?!е)\b",
        "на ютубе",
        text
    )

    # Дополнительные варианты
    text = re.sub(
        r"\bютубее\b",
        "ютубе",
        text
    )

    text = re.sub(
        r"\bютубе{2,}\b",
        "ютубе",
        text
    )

    return text.strip()


def remove_wake_word(text: str, wake_words=None):
    words = text.split()

    result = []
    has_jarvis = False

    for word in words:
        if _is_wake_word(word, wake_words):
            has_jarvis = True
            continue

        result.append(word)

    return " ".join(result).strip(), has_jarvis


def process_voice_text(text: str, wake_words=None):
    normalized = normalize_text(text)

    prompt, has_jarvis = remove_wake_word(
        normalized,
        wake_words=wake_words,
    )

    return prompt, has_jarvis