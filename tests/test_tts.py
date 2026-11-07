import unittest
from unittest.mock import patch

from app.main import get_tts_config
from app.tts import TTS


class TTSTests(unittest.TestCase):

    def test_edge_failure_returns_false_without_local_fallback(self):
        tts = TTS(rate=185)

        def fail(coroutine):
            coroutine.close()
            raise RuntimeError("HTTP 403")

        with patch("app.tts.asyncio.run", side_effect=fail):
            result = tts.speak("Проверка озвучивания")

        self.assertFalse(result)

    def test_edge_failure_uses_offline_fallback_when_enabled(self):
        tts = TTS(offline_fallback=True)

        def fail(coroutine):
            coroutine.close()
            raise RuntimeError("HTTP 403")

        with (
            patch("app.tts.asyncio.run", side_effect=fail),
            patch.object(
                tts,
                "_speak_offline",
                return_value=True,
            ) as offline,
        ):
            result = tts.speak("Проверка офлайн")

        self.assertTrue(result)
        offline.assert_called_once_with("Проверка офлайн")

    def test_edge_failure_tries_next_voice(self):
        tts = TTS(voices=["en-US-AndrewNeural"])
        calls = 0

        def fail_once_then_succeed(coroutine):
            nonlocal calls
            calls += 1
            coroutine.close()
            if calls == 1:
                raise RuntimeError("temporary connection error")

        with patch(
            "app.tts.asyncio.run",
            side_effect=fail_once_then_succeed,
        ) as edge_run:
            result = tts.speak("Ответ")

        self.assertTrue(result)
        self.assertEqual(edge_run.call_count, 2)
        self.assertEqual(
            tts.voices,
            [
                "en-US-AndrewMultilingualNeural",
                "en-US-AndrewNeural",
            ],
        )

    def test_default_voice_is_multilingual_male_edge_voice(self):
        tts = TTS()

        self.assertEqual(
            tts.voice,
            "en-US-AndrewMultilingualNeural",
        )
        self.assertEqual(
            get_tts_config({})["voice"],
            "en-US-AndrewMultilingualNeural",
        )

    def test_tts_voice_can_be_configured(self):
        self.assertEqual(
            get_tts_config(
                {"tts_voice": "ru-RU-DmitryNeural"}
            )["voice"],
            "ru-RU-DmitryNeural",
        )
        self.assertEqual(
            get_tts_config(
                {"tts": {"voice": "en-US-AvaMultilingualNeural"}}
            )["voice"],
            "en-US-AvaMultilingualNeural",
        )

    def test_voices_list_is_configured(self):
        config = get_tts_config(
            {
                "tts_voice": "en-US-AndrewMultilingualNeural",
                "tts_voices": [
                    "en-US-AndrewMultilingualNeural",
                    "en-GB-RyanNeural",
                ],
            }
        )

        self.assertEqual(
            config["voices"],
            [
                "en-US-AndrewMultilingualNeural",
                "en-GB-RyanNeural",
            ],
        )

    def test_successful_edge_speech_returns_true(self):
        tts = TTS()

        def finish_without_network(coroutine):
            coroutine.close()

        with patch(
            "app.tts.asyncio.run",
            side_effect=finish_without_network,
        ):
            result = tts.speak("Проверка")

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
