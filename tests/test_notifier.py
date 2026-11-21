"""Тесты Telegram-уведомлений (без реальных сетевых вызовов)."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from app import notifier


class _SyncThread:
    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.target = target
        self.args = args

    def start(self):
        if self.target is not None:
            self.target(*self.args)


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = Path(self._tmp.name) / "config.json"
        patcher = patch.object(notifier, "CONFIG_FILE", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        notifier._config_cache.clear()
        notifier._config_cache.update(
            {"mtime": 0.0, "data": {}, "file_mtime": -1.0}
        )
        env = patch.dict(
            os.environ,
            {
                "JARVIS_TELEGRAM_BOT_TOKEN": "",
                "JARVIS_TELEGRAM_CHAT_ID": "",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def _write_config(self, payload):
        self.config.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_disabled_by_default(self):
        self._write_config({})
        with patch.object(notifier, "_send") as send:
            notifier.notify("привет")
        send.assert_not_called()

    def test_enabled_without_credentials_skips(self):
        self._write_config({"notifications": {"telegram": True}})
        with patch.object(notifier, "_send") as send:
            notifier.notify("привет")
        send.assert_not_called()

    def test_enabled_sends_with_env_credentials(self):
        self._write_config(
            {"notifications": {"telegram": True, "tasks": True}}
        )
        os.environ["JARVIS_TELEGRAM_BOT_TOKEN"] = "bot-token"
        os.environ["JARVIS_TELEGRAM_CHAT_ID"] = "42"
        with patch.object(
            notifier.threading, "Thread", _SyncThread
        ), patch.object(notifier, "_send") as send:
            notifier.notify("готово", kind="tasks")
        send.assert_called_once_with("bot-token", "42", "готово")

    def test_error_kind_filtered_by_config(self):
        self._write_config(
            {
                "notifications": {
                    "telegram": True,
                    "tasks": True,
                    "errors": False,
                }
            }
        )
        os.environ["JARVIS_TELEGRAM_BOT_TOKEN"] = "bot-token"
        os.environ["JARVIS_TELEGRAM_CHAT_ID"] = "42"
        with patch.object(notifier, "_send") as send:
            notifier.notify("ошибка", kind="errors")
        send.assert_not_called()

    def test_send_posts_and_truncates(self):
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(
            notifier.requests, "post", return_value=response
        ) as post:
            result = notifier._send("token", "chat", "x" * 5000)
        self.assertTrue(result)
        url = post.call_args.args[0]
        self.assertIn("token", url)
        body = post.call_args.kwargs["json"]
        self.assertEqual(len(body["text"]), 4000)

    def test_send_failure_returns_false(self):
        with patch.object(
            notifier.requests,
            "post",
            side_effect=OSError("network down"),
        ):
            self.assertFalse(notifier._send("t", "c", "x"))

    def test_notify_task_maps_status_to_kind(self):
        with patch.object(notifier, "notify") as notify:
            notifier.notify_task("Задача", "done", "ok")
            notifier.notify_task("Задача", "failed", "bad")
        first = notify.call_args_list[0].kwargs["kind"]
        second = notify.call_args_list[1].kwargs["kind"]
        self.assertEqual(first, "tasks")
        self.assertEqual(second, "errors")


if __name__ == "__main__":
    unittest.main()
