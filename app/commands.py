import datetime
import re


def normalize_command(text: str) -> str:
    if not text:
        return ""

    text = text.lower().strip()
    text = re.sub(r"[^\w\s\-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _time_answer(address):
    now = datetime.datetime.now()
    return f"Сейчас {now.hour:02d}:{now.minute:02d}, {address}."


def _date_answer(address):
    now = datetime.datetime.now()
    weekdays = (
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    )
    return (
        f"Сегодня {now.day:02d}.{now.month:02d}.{now.year}, "
        f"{weekdays[now.weekday()]}, {address}."
    )


def handle_command(text: str, memory=None):
    raw_text = str(text or "").strip()
    text = normalize_command(text)

    if not text:
        return None

    address = "сэр"

    exit_commands = {
        "выход",
        "выйди",
        "заверши работу",
        "остановись",
        "закрой джарвис",
        "выключи джарвис",
        "отключись",
        "выключись",
        "пока",
        "до свидания",
    }

    if text in exit_commands:
        return "__EXIT__"

    time_commands = {
        "который час",
        "сколько времени",
        "текущее время",
        "скажи время",
    }

    if text in time_commands:
        return _time_answer(address)

    date_commands = {
        "какая сегодня дата",
        "сегодняшняя дата",
        "какое сегодня число",
        "назови дату",
    }

    if text in date_commands:
        return _date_answer(address)

    if text in {
        "привет",
        "здравствуй",
        "здравствуйте",
        "добрый день",
        "доброе утро",
        "добрый вечер",
    }:
        return "Приветствую, сэр. Чем могу помочь?"

    if text in {
        "как дела",
        "как ты",
        "как система",
    }:
        return (
            "Все системы функционируют штатно, сэр. "
            "Благодарю за вопрос."
        )

    if text in {
        "кто ты",
        "что ты такое",
        "представься",
    }:
        return (
            "Я JARVIS — Just A Rather Very Intelligent System. "
            "К вашим услугам, сэр."
        )

    if text in {
        "что ты умеешь",
        "твои возможности",
        "список команд",
    }:
        return (
            "Я управляю окнами и приложениями, громкостью, "
            "браузером и YouTube, ищу файлы, ставлю таймеры, "
            "проверяю состояние системы и работаю с экраном. "
            "Скажите, что требуется, сэр."
        )

    if text in {
        "спасибо",
        "благодарю",
    }:
        return "Всегда к вашим услугам, сэр."

    remember_match = re.match(
        r"^(?:запомни(?:,?\s+что)?|запиши)\s+(.+)$",
        raw_text,
        re.IGNORECASE,
    )

    if remember_match:
        fact = remember_match.group(1).strip()
        if memory is None:
            return "Модуль памяти недоступен, сэр."

        if memory.remember(fact):
            return f"Запомнил, сэр: {fact}."

        return "Это уже есть в моей памяти, сэр."

    name_match = re.match(
        r"^(?:меня зовут|моё имя|мое имя)\s+(.+)$",
        raw_text,
        re.IGNORECASE,
    )

    if name_match:
        name = name_match.group(1).strip()
        if memory is not None:
            memory.set_profile("Имя пользователя", name)
        return f"Приятно познакомиться, {name}."

    if text in {
        "что ты помнишь",
        "что ты знаешь обо мне",
        "мои данные",
    }:
        if memory is None:
            return "Модуль памяти недоступен, сэр."

        summary = memory.summary()
        return summary or "Пока я ничего о вас не запомнил, сэр."

    if text in {
        "забудь всё",
        "забудь все",
        "очисти память",
    }:
        if memory is None:
            return "Модуль памяти недоступен, сэр."

        memory.forget_all()
        return "Память очищена, сэр."

    return None
