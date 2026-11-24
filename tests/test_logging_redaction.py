"""Редакция секретов в логах."""

import logging
import unittest

from app.logging import _RedactFilter


def _record(message, args=()):
    return logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        message,
        args,
        None,
    )


class RedactFilterTests(unittest.TestCase):
    def test_query_token_redacted(self):
        record = _record("GET /?token=abc123 200")
        _RedactFilter().filter(record)
        self.assertNotIn("abc123", record.getMessage())
        self.assertIn("token=***", record.getMessage())

    def test_bearer_token_redacted(self):
        record = _record("Authorization: Bearer secret-value")
        _RedactFilter().filter(record)
        self.assertNotIn("secret-value", record.getMessage())

    def test_cookie_token_redacted(self):
        record = _record("Cookie: jarvis_token=abc; Path=/")
        _RedactFilter().filter(record)
        self.assertNotIn("jarvis_token=abc", record.getMessage())

    def test_api_key_redacted(self):
        record = _record("key sk-ABCDEFGHIJKLMNOPQRSTUV end")
        _RedactFilter().filter(record)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", record.getMessage())

    def test_args_are_redacted(self):
        record = _record("url=%s", ("http://x/?token=leak",))
        _RedactFilter().filter(record)
        self.assertNotIn("leak", record.getMessage())

    def test_telegram_token_redacted(self):
        token = "123456789:" + "A" * 35
        record = _record(f"bot token {token} end")
        _RedactFilter().filter(record)
        self.assertNotIn(token, record.getMessage())
        self.assertIn("***", record.getMessage())

    def test_normal_text_untouched(self):
        record = _record("Токен создан, всё хорошо")
        _RedactFilter().filter(record)
        self.assertEqual(
            record.getMessage(),
            "Токен создан, всё хорошо",
        )


if __name__ == "__main__":
    unittest.main()
