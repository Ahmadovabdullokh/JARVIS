import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.listener import VoiceListener


class FakeTranscriptions:

    def __init__(self, fail_with_prompt=False):
        self.fail_with_prompt = fail_with_prompt
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        if self.fail_with_prompt and "prompt" in kwargs:
            raise RuntimeError("prompt is not supported")

        return SimpleNamespace(
            text="Джарвис, открой блокнот"
        )


class FakeClient:

    def __init__(self, transcriptions):
        self.audio = SimpleNamespace(
            transcriptions=transcriptions
        )


class ListenerTests(unittest.TestCase):

    def make_listener(self, transcriptions):
        listener = VoiceListener(
            api_key="test",
            prompt="Джарвис, открой браузер.",
        )
        listener.client = FakeClient(transcriptions)
        return listener

    def test_prompt_is_sent_to_groq(self):
        transcriptions = FakeTranscriptions()
        listener = self.make_listener(transcriptions)

        result = listener._transcribe(
            np.zeros(1600, dtype=np.float32)
        )

        self.assertEqual(result, "Джарвис, открой блокнот")
        self.assertEqual(len(transcriptions.calls), 1)
        self.assertEqual(
            transcriptions.calls[0]["prompt"],
            "Джарвис, открой браузер.",
        )

    def test_local_stt_allows_missing_groq_key(self):
        with patch.dict("sys.modules", {"faster_whisper": None}):
            listener = VoiceListener(
                api_key="",
                local_model="small",
            )
        self.assertIsNone(listener.client)
        self.assertIsNone(listener.local_model)

    def test_local_stt_transcription(self):
        with patch.dict("sys.modules", {"faster_whisper": None}):
            listener = VoiceListener(
                api_key="",
                local_model="small",
            )
        listener.local_model = SimpleNamespace(
            transcribe=lambda *args, **kwargs: (
                [SimpleNamespace(text="локальный текст")],
                None,
            )
        )
        result = listener._transcribe(
            np.zeros(1600, dtype=np.float32)
        )
        self.assertEqual(result, "локальный текст")

    def test_transcription_retries_without_prompt(self):
        transcriptions = FakeTranscriptions(
            fail_with_prompt=True
        )
        listener = self.make_listener(transcriptions)

        result = listener._transcribe(
            np.zeros(1600, dtype=np.float32)
        )

        self.assertEqual(result, "Джарвис, открой блокнот")
        self.assertEqual(len(transcriptions.calls), 2)
        self.assertIn("prompt", transcriptions.calls[0])
        self.assertNotIn("prompt", transcriptions.calls[1])


class FakeStream:

    def __init__(self, callback=None, **kwargs):
        self.callback = callback
        self.kwargs = kwargs
        self.active = False
        self.stopped = 0
        self.closed = 0

    def start(self):
        self.active = True
        if self.callback is not None:
            block = np.full((800, 1), 0.25, dtype=np.float32)
            self.callback(block, 800, None, None)

    def stop(self):
        self.stopped += 1
        self.active = False

    def close(self):
        self.closed += 1


class MeterStreamTests(unittest.TestCase):

    def make_listener(self, streams):
        def fake_input_stream(**kwargs):
            stream = FakeStream(**kwargs)
            streams.append(stream)
            return stream

        listener = VoiceListener(api_key="test")
        patcher = patch(
            "app.listener.sd.InputStream",
            side_effect=fake_input_stream,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(listener.close_meter)
        return listener

    def test_meter_stream_is_opened_once_and_reused(self):
        streams = []
        listener = self.make_listener(streams)

        levels = [listener.measure_level(0.15) for _ in range(20)]

        self.assertEqual(len(streams), 1)
        self.assertTrue(all(level == 0.25 for level in levels))

    def test_inactive_stream_is_replaced(self):
        streams = []
        listener = self.make_listener(streams)
        listener.measure_level()
        streams[0].active = False

        listener.measure_level()

        self.assertEqual(len(streams), 2)

    def test_disabled_microphone_returns_zero(self):
        streams = []
        listener = self.make_listener(streams)
        listener.measure_level()
        listener.mic_disabled = True

        self.assertEqual(listener.measure_level(), 0.0)

    def test_close_meter_releases_stream(self):
        streams = []
        listener = self.make_listener(streams)
        listener.measure_level()

        listener.close_meter()

        self.assertEqual(streams[0].stopped, 1)
        self.assertEqual(streams[0].closed, 1)


if __name__ == "__main__":
    unittest.main()
