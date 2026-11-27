import json
import re
import unittest
from datetime import datetime

from app import persona
from app.config import get_wake_config
from app.paths import BASE_DIR, EXAMPLE_CONFIG_FILE

NON_ASCII_RUN = re.compile(r"[^\x00-\x7f]+")
TEXT_SUFFIXES = {".py", ".json", ".js", ".css", ".html", ".webmanifest"}
SCAN_DIRS = ("app", "config", "ui")


def has_cyrillic(text):
    return any("Ѐ" <= char <= "ӿ" for char in text)


def is_mojibake_run(run):
    """True if this non-ASCII run is UTF-8 text misread as cp1251."""
    if not has_cyrillic(run):
        return False
    try:
        decoded = run.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    return has_cyrillic(decoded)


def mojibake_runs(text):
    return [run for run in NON_ASCII_RUN.findall(text) if is_mojibake_run(run)]


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def text_sources():
    for dirname in SCAN_DIRS:
        base = BASE_DIR / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            yield path


class TextSourceEncodingTests(unittest.TestCase):

    def test_text_sources_are_valid_utf8(self):
        problems = []
        for path in text_sources():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                problems.append(f"{path.relative_to(BASE_DIR)}: {error}")
                continue
            if "�" in text:
                problems.append(
                    f"{path.relative_to(BASE_DIR)}: contains U+FFFD"
                )

        self.assertEqual(problems, [], "\n".join(problems))

    def test_text_sources_have_no_cp1251_mojibake(self):
        problems = []
        for path in text_sources():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # уже отражено в test_text_sources_are_valid_utf8
            for lineno, line in enumerate(text.splitlines(), 1):
                for run in mojibake_runs(line):
                    fixed = run.encode("cp1251").decode("utf-8")
                    problems.append(
                        f"{path.relative_to(BASE_DIR)}:{lineno}: "
                        f"{run!r} -> {fixed!r}"
                    )

        self.assertEqual(problems, [], "\n".join(problems[:10]))


class ExampleConfigEncodingTests(unittest.TestCase):

    def setUp(self):
        self.config = json.loads(
            EXAMPLE_CONFIG_FILE.read_text(encoding="utf-8")
        )

    def test_user_facing_strings_are_clean(self):
        self.assertEqual(self.config["wake_ack"], "Слушаю, сэр.")
        self.assertEqual(self.config["persona"]["address"], "сэр")
        self.assertEqual(
            self.config["wake_words"],
            ["джарвис", "jarvis", "джарвиз", "дарвис"],
        )
        self.assertTrue(
            self.config["stt_prompt"].startswith(
                "Джарвис, открой браузер."
            )
        )

    def test_all_config_strings_are_free_of_mojibake(self):
        problems = []
        for value in iter_strings(self.config):
            for run in mojibake_runs(value):
                fixed = run.encode("cp1251").decode("utf-8")
                problems.append(f"{run!r} -> {fixed!r}")

        self.assertEqual(problems, [], "\n".join(problems[:10]))


class RuntimeDefaultsEncodingTests(unittest.TestCase):

    def test_default_wake_words_are_clean(self):
        self.assertEqual(
            get_wake_config({})["wake_words"],
            ["джарвис", "jarvis", "джарвиз", "дарвис"],
        )


class PersonaEncodingTests(unittest.TestCase):

    def test_persona_rendering_from_example_config_is_clean(self):
        config = json.loads(
            EXAMPLE_CONFIG_FILE.read_text(encoding="utf-8")
        )
        now = datetime(2026, 11, 26, 20)

        startup = persona.startup_line(config, now=now)

        self.assertTrue(startup.startswith("Добрый вечер, сэр."))
        self.assertIn("Все системы в норме.", startup)
        self.assertEqual(
            persona.address_result("Открываю Telegram.", config),
            "Сэр, открываю Telegram.",
        )
        self.assertEqual(persona.wake_ack(config), "Слушаю, сэр.")
