import asyncio
import os
import re
import subprocess
import threading

import edge_tts
import imageio_ffmpeg
import sounddevice as sd

from app.logging import get_logger
from app.persona import clean_for_speech

log = get_logger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# Голоса Edge TTS на случай, если заданный в конфиге недоступен (403).
FALLBACK_VOICES = ("ru-RU-DmitryNeural", "en-US-GuyNeural")


def _hidden_window_kwargs():
    """Kwargs to spawn console subprocesses without a visible console window."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def split_sentences(text: str, max_chars: int = 400):
    """Делит текст на предложения для потоковой озвучки.

    Длинные предложения без знаков препинания режутся по max_chars,
    чтобы первая фраза начала звучать как можно раньше.
    """

    parts = []
    for chunk in _SENTENCE_SPLIT.split(text):
        chunk = chunk.strip()
        while len(chunk) > max_chars:
            cut = chunk.rfind(" ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            parts.append(chunk[:cut].strip())
            chunk = chunk[cut:].strip()
        if chunk:
            parts.append(chunk)
    return parts or [text]


class TTS:
    def __init__(
        self,
        rate: int = 175,
        voice: str = "en-US-AndrewMultilingualNeural",
        pitch: str = "-8Hz",
        voices=None,
        offline_fallback: bool = True,
        output_device=None,
        stream_sentences: bool = True,
    ):
        self.voice = voice
        self.pitch = pitch
        self.rate_value = rate
        self.rate = self._convert_rate(rate)
        self.offline_fallback = bool(offline_fallback)
        self.output_device = output_device
        self.stream_sentences = bool(stream_sentences)

        self.sample_rate = 24000
        self.channels = 1

        ordered = [voice]
        for item in voices or []:
            item = str(item).strip()
            if item and item not in ordered:
                ordered.append(item)
        for item in FALLBACK_VOICES:
            if item not in ordered:
                ordered.append(item)
        self.voices = ordered

        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        self._process = None
        self._process_lock = threading.Lock()
        self._stop_event = threading.Event()

        device_info = (
            f", устройство: {output_device}" if output_device else ""
        )
        log.info("[TTS] Streaming Edge TTS")
        log.info(f"[TTS] Голоса: {', '.join(self.voices)}")
        log.info(f"[TTS] Скорость: {self.rate}")
        log.info(f"[TTS] Pitch: {self.pitch}{device_info}")
        log.info(f"[TTS] FFmpeg: {self.ffmpeg}")

    def _convert_rate(self, rate: int) -> str:
        difference = rate - 175
        percent = int(difference / 175 * 100)

        percent = max(-50, min(50, percent))

        return f"{percent:+d}%"

    def _resolve_device(self):
        if not self.output_device:
            return None
        try:
            devices = sd.query_devices()
            wanted = str(self.output_device).strip().lower()
            for index, device in enumerate(devices):
                name = str(device.get("name", "")).lower()
                if wanted == str(index) or wanted in name:
                    return index
            log.info(
                f"[TTS] Устройство {self.output_device!r} не найдено, "
                "используется устройство по умолчанию."
            )
        except Exception as error:
            log.info(f"[TTS] Не удалось выбрать устройство: {error}")
        return None

    def _play_pcm(self, process):
        try:
            with sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=1024,
                device=self._resolve_device(),
            ) as stream:
                while not self._stop_event.is_set():
                    if process.stdout is None or process.stdout.closed:
                        break
                    try:
                        data = process.stdout.read(4096)
                    except (ValueError, OSError):
                        break

                    if not data:
                        break

                    stream.write(data)

        except Exception as error:
            log.info(f"[TTS AUDIO ERROR] {error}")

    def _spawn_ffmpeg(self):
        process = subprocess.Popen(
            [
                self.ffmpeg,
                "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "s16le",
                "-ar", str(self.sample_rate),
                "-ac", str(self.channels),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            **_hidden_window_kwargs(),
        )
        with self._process_lock:
            self._process = process
        return process

    def _close_process(self, process, close_stdout=True):
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass
        try:
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if close_stdout:
            try:
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
            except Exception:
                pass
        with self._process_lock:
            if self._process is process:
                self._process = None

    async def _stream_sentence(self, sentence: str, voice: str):
        """Озвучивает одно предложение: edge-tts -> ffmpeg -> PCM."""

        self._stop_event.clear()
        process = self._spawn_ffmpeg()

        player_thread = threading.Thread(
            target=self._play_pcm,
            args=(process,),
            daemon=True,
        )
        player_thread.start()

        try:
            communicate = edge_tts.Communicate(
                text=sentence,
                voice=voice,
                rate=self.rate,
                volume="+0%",
                pitch=self.pitch,
            )

            async for chunk in communicate.stream():
                if self._stop_event.is_set():
                    break
                if chunk["type"] != "audio":
                    continue

                audio_data = chunk["data"]
                if not audio_data:
                    continue

                try:
                    process.stdin.write(audio_data)
                    process.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    break

        finally:
            self._close_process(process, close_stdout=False)
            player_thread.join(timeout=5)
            try:
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
            except Exception:
                pass

    async def _speak_async(self, text: str, voice: str, progress=None):
        sentences = (
            split_sentences(text) if self.stream_sentences else [text]
        )
        start = int((progress or {}).get("done", 0))
        for index, sentence in enumerate(sentences):
            if index < start:
                continue
            if self._stop_event.is_set():
                break
            await self._stream_sentence(sentence, voice)
            if progress is not None:
                progress["done"] = index + 1

    def stop(self):
        """Прерывает текущее воспроизведение (barge-in)."""

        self._stop_event.set()
        with self._process_lock:
            process = self._process
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass

    def _speak_offline(self, text: str) -> bool:
        try:
            import pyttsx3
        except Exception:
            log.info("[TTS] pyttsx3 не установлен.")
            return False
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", int(self.rate_value or 175))
            engine.say(text)
            engine.runAndWait()
            log.info("[TTS] Офлайн-синтез выполнен.")
            return True
        except Exception as error:
            log.info(f"[TTS OFFLINE ERROR] {error}")
            return False

    def speak(self, text: str) -> bool:
        text = clean_for_speech(text)

        if not text:
            return True

        self._stop_event.clear()
        log.info(f"[TTS] Говорю: {text}")

        progress = {"done": 0}
        for voice in self.voices:
            try:
                asyncio.run(
                    self._speak_async(text, voice, progress)
                )
                if self._stop_event.is_set():
                    log.info("[TTS] Воспроизведение прервано.")
                    return True
                log.info("[TTS] Готово.")
                return True

            except Exception as error:
                log.info(
                    f"[TTS] Edge TTS недоступен для голоса "
                    f"{voice} ({type(error).__name__}: {error})."
                )

        if self.offline_fallback:
            log.info("[TTS] Пробую офлайн-синтез.")
            if self._speak_offline(text):
                return True

        log.info("[TTS ERROR] Облачная озвучка недоступна.")
        return False
