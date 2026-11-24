import asyncio
import unittest
from unittest.mock import patch

from app.main import get_tts_config
from app.tts import TTS, _is_male_offline_voice, split_sentences


class TTSTests(unittest.TestCase):

    def test_edge_failure_returns_false_without_local_fallback(self):
        tts = TTS(rate=185, offline_fallback=False)

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

        def fail_first_voice(coroutine):
            nonlocal calls
            calls += 1
            coroutine.close()
            if calls <= 2:
                raise RuntimeError("temporary connection error")

        with patch(
            "app.tts.asyncio.run",
            side_effect=fail_first_voice,
        ) as edge_run:
            result = tts.speak("тест")

        self.assertTrue(result)
        self.assertEqual(edge_run.call_count, 3)
        self.assertEqual(
            tts.voices,
            [
                "en-US-BrianMultilingualNeural",
                "en-US-AndrewNeural",
                "en-US-AndrewMultilingualNeural",
            ],
        )

    def test_default_voice_is_multilingual_male_edge_voice(self):
        tts = TTS()

        self.assertEqual(
            tts.voice,
            "en-US-BrianMultilingualNeural",
        )
        self.assertEqual(
            get_tts_config({})["voice"],
            "en-US-BrianMultilingualNeural",
        )
        self.assertEqual(get_tts_config({})["pitch"], "-12Hz")

    def test_blocked_voices_are_skipped(self):
        tts = TTS(
            voice="ru-RU-DmitryNeural",
            voices=["ru-RU-SvetlanaNeural"],
        )

        self.assertEqual(
            tts.voices,
            [
                "en-US-BrianMultilingualNeural",
                "en-US-AndrewMultilingualNeural",
            ],
        )

    def test_failed_voice_is_skipped_on_next_utterance(self):
        tts = TTS(
            voice="en-US-AndrewMultilingualNeural",
            voices=["en-US-BrianMultilingualNeural"],
            offline_fallback=False,
        )
        calls = []

        async def fake_speak(text, voice):
            calls.append(voice)
            if voice == "en-US-AndrewMultilingualNeural":
                raise RuntimeError("temporary failure")

        with patch.object(tts, "_speak_async", side_effect=fake_speak):
            self.assertTrue(tts.speak("Первый раз"))
            self.assertTrue(tts.speak("Второй раз"))

        self.assertEqual(
            calls,
            [
                "en-US-AndrewMultilingualNeural",
                "en-US-BrianMultilingualNeural",
                "en-US-BrianMultilingualNeural",
            ],
        )

    def test_multi_sentence_text_uses_one_stream(self):
        tts = TTS()
        calls = []

        async def fake_stream(text, voice):
            calls.append((text, voice))

        with patch.object(tts, "_stream_sentence", new=fake_stream):
            asyncio.run(
                tts._speak_async(
                    "Первое. Второе! Третье?",
                    "en-US-AndrewMultilingualNeural",
                )
            )

        self.assertEqual(
            calls,
            [
                (
                    "Первое. Второе! Третье?",
                    "en-US-AndrewMultilingualNeural",
                )
            ],
        )

    def test_offline_voice_must_be_male(self):
        class Voice:
            def __init__(self, name):
                self.id = name
                self.name = name
                self.gender = None
                self.languages = []

        self.assertFalse(
            _is_male_offline_voice(
                Voice("Microsoft Irina Desktop - Russian")
            )
        )
        self.assertTrue(
            _is_male_offline_voice(
                Voice("Microsoft Pavel - Russian")
            )
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

    def test_offline_fallback_is_enabled_by_default(self):
        self.assertTrue(TTS().offline_fallback)

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


class SplitSentencesTests(unittest.TestCase):

    def test_splits_on_sentence_endings(self):
        parts = split_sentences("Первое. Второе! Третье?")
        self.assertEqual(parts, ["Первое.", "Второе!", "Третье?"])

    def test_single_sentence_stays_whole(self):
        self.assertEqual(
            split_sentences("Одна фраза без точки"),
            ["Одна фраза без точки"],
        )

    def test_long_sentence_is_cut_by_words(self):
        text = " ".join(["слово"] * 200)
        parts = split_sentences(text, max_chars=100)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 100 for p in parts))

    def test_empty_text_returns_original(self):
        self.assertEqual(split_sentences(""), [""])


if __name__ == "__main__":
    unittest.main()
