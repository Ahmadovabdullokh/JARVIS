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


if __name__ == "__main__":
    unittest.main()
