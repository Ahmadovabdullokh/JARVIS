import asyncio
import os
import re
import subprocess
import threading
import time

import imageio_ffmpeg
import sounddevice as sd

from app.logging import get_logger
from app.persona import clean_for_speech

log = get_logger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# JARVIS должен оставаться мужским. Женские и заведомо мёртвые
# голоса не попадают в цепочку даже как fallback.
# ru-RU-DmitryNeural стабильно отдаёт NoAudioReceived, поэтому
# базовые голоса — мужские мультиязычные Edge-голоса.
FALLBACK_VOICES = (
    "en-US-BrianMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
)

BLOCKED_VOICES = {
    "ru-RU-DmitryNeural",       # NoAudioReceived
    "ru-RU-SvetlanaNeural",     # женский
    "ru-RU-IrinaNeural",        # женский
    "en-US-AriaNeural",         # женский
    "en-US-JennyNeural",        # женский
    "en-GB-SoniaNeural",        # женский
}

VOICE_FAILURE_TTL = 600

OFFLINE_MALE_MARKERS = (
    "male",
    "pavel",
    "dmitry",
    "dmitri",
    "ruslan",
    "yuri",
    "yuriy",
    "maxim",
    "artem",
    "aidar",
)

OFFLINE_FEMALE_MARKERS = (
    "female",
    "irina",
    "svetlana",
    "zira",
    "aria",
    "jenny",
    "sonia",
)


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


def _voice_text(voice) -> str:
    return (
        f"{getattr(voice, 'id', '')} "
        f"{getattr(voice, 'name', '')} "
        f"{getattr(voice, 'gender', '')}"
    ).lower()


def _is_male_offline_voice(voice) -> bool:
    text = _voice_text(voice)
    if any(marker in text for marker in OFFLINE_FEMALE_MARKERS):
        return False
    if str(getattr(voice, "gender", "") or "").strip().lower() == "male":
        return True
    return any(marker in text for marker in OFFLINE_MALE_MARKERS)


def _is_russian_voice(voice) -> bool:
    text = _voice_text(voice)
    languages = " ".join(
        str(item)
        for item in (getattr(voice, "languages", []) or [])
    ).lower()
    return (
        "russian" in text
        or "ru-ru" in text
        or "ru_ru" in text
        or languages.startswith("ru")
        or "ru_" in languages
        or "ru-ru" in languages
    )


class TTS:
    def __init__(
        self,
        rate: int = 175,
        voice: str = "en-US-BrianMultilingualNeural",
        pitch: str = "-12Hz",
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

        ordered = []
        for item in [voice, *(voices or [])]:
            item = str(item).strip()
            if not item or item in ordered:
                continue
            if item in BLOCKED_VOICES:
                log.info(
                    f"[TTS] Голос {item} отключён: "
                    "женский или недоступный."
                )
                continue
            ordered.append(item)
        for item in FALLBACK_VOICES:
            if item not in ordered:
                ordered.append(item)
        self.voices = ordered

        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        self._process = None
        self._process_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._voice_failures = {}

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

    def _voices_to_try(self):
        now = time.monotonic()
        usable = [
            voice
            for voice in self.voices
            if self._voice_failures.get(voice, 0) <= now
        ]
        if usable:
            return usable
        log.info(
            "[TTS] Все голоса недавно падали; "
            "пропускаю Edge до истечения паузы."
        )
        return []

    def _mark_voice_failed(self, voice):
        self._voice_failures[voice] = (
            time.monotonic() + VOICE_FAILURE_TTL
        )

    def _play_pcm(self, process, result):
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
                    result["bytes"] += len(data)

        except Exception as error:
            result["error"] = error
            log.info(f"[TTS AUDIO ERROR] {error}")

    def _spawn_ffmpeg(self):
        process = subprocess.Popen(
            [
                self.ffmpeg,
                "-loglevel", "error",
                "-probesize", "32k",
                "-analyzeduration", "0",
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
        """Озвучивает весь текст: edge-tts -> ffmpeg -> PCM.

        Один WebSocket и один ffmpeg на фразу дают непрерывную
        речь без пауз между предложениями.
        """

        # edge-tts тянет за собой ~0.8 с импорта; грузим только
        # при первой реальной озвучке.
        import edge_tts

        started = time.monotonic()
        first_audio_at = None
        process = self._spawn_ffmpeg()
        played = {"bytes": 0, "error": None}

        player_thread = threading.Thread(
            target=self._play_pcm,
            args=(process, played),
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
                connect_timeout=6,
                receive_timeout=20,
            )

            async for chunk in communicate.stream():
                if self._stop_event.is_set():
                    break
                if chunk["type"] != "audio":
                    continue

                audio_data = chunk["data"]
                if not audio_data:
                    continue

                if first_audio_at is None:
                    first_audio_at = time.monotonic() - started
                    log.info(
                        f"[TTS] Первое аудио через "
                        f"{first_audio_at:.2f} с (голос {voice})."
                    )

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

        if (
            not self._stop_event.is_set()
            and played["bytes"] == 0
            and played["error"] is not None
        ):
            raise RuntimeError(f"аудиовыход: {played['error']}")

    async def _speak_async(self, text: str, voice: str, progress=None):
        await self._stream_sentence(text, voice)
        if progress is not None:
            progress["done"] = 1

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
            chosen = None
            for voice in engine.getProperty("voices") or []:
                if not _is_male_offline_voice(voice):
                    continue
                if not _is_russian_voice(voice):
                    continue
                chosen = voice
                break
            if chosen is None:
                log.info(
                    "[TTS] Мужской русский офлайн-голос не найден; "
                    "женский fallback отключён."
                )
                return False
            engine.setProperty("voice", chosen.id)
            log.info(
                f"[TTS] Офлайн-голос: "
                f"{getattr(chosen, 'name', chosen.id)}"
            )
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

        for voice in self._voices_to_try():
            if self._stop_event.is_set():
                log.info("[TTS] Воспроизведение прервано.")
                return True
            started = time.monotonic()
            try:
                asyncio.run(self._speak_async(text, voice))
                if self._stop_event.is_set():
                    log.info("[TTS] Воспроизведение прервано.")
                    return True
                self._voice_failures.pop(voice, None)
                log.info(
                    f"[TTS] Готово за "
                    f"{time.monotonic() - started:.1f} с "
                    f"(голос {voice})."
                )
                return True

            except Exception as error:
                if self._stop_event.is_set():
                    log.info("[TTS] Воспроизведение прервано.")
                    return True
                elapsed = time.monotonic() - started
                self._mark_voice_failed(voice)
                log.info(
                    f"[TTS] Голос {voice} недоступен за "
                    f"{elapsed:.1f} с "
                    f"({type(error).__name__}: {error})."
                )

        if self.offline_fallback:
            log.info("[TTS] Пробую офлайн-синтез.")
            if self._speak_offline(text):
                return True

        log.info("[TTS ERROR] Облачная озвучка недоступна.")
        return False
