import asyncio
import subprocess
import threading

import edge_tts
import imageio_ffmpeg
import sounddevice as sd

from app.logging import get_logger
from app.persona import clean_for_speech

log = get_logger(__name__)


class TTS:
    def __init__(
        self,
        rate: int = 175,
        voice: str = "en-US-AndrewMultilingualNeural",
        pitch: str = "-8Hz",
        voices=None,
        offline_fallback: bool = False,
    ):
        self.voice = voice
        self.pitch = pitch
        self.rate_value = rate
        self.rate = self._convert_rate(rate)
        self.offline_fallback = bool(offline_fallback)

        self.sample_rate = 24000
        self.channels = 1

        ordered = [voice]
        for item in voices or []:
            item = str(item).strip()
            if item and item not in ordered:
                ordered.append(item)
        self.voices = ordered

        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        log.info("[TTS] Streaming Edge TTS")
        log.info(f"[TTS] Голоса: {', '.join(self.voices)}")
        log.info(f"[TTS] Скорость: {self.rate}")
        log.info(f"[TTS] Pitch: {self.pitch}")
        log.info(f"[TTS] FFmpeg: {self.ffmpeg}")

    def _convert_rate(self, rate: int) -> str:
        difference = rate - 175
        percent = int(difference / 175 * 100)

        percent = max(-50, min(50, percent))

        return f"{percent:+d}%"

    def _play_pcm(self, process):
        try:
            with sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=1024,
            ) as stream:
                while True:
                    data = process.stdout.read(4096)

                    if not data:
                        break

                    stream.write(data)

        except Exception as error:
            log.info(f"[TTS AUDIO ERROR] {error}")

    async def _speak_async(self, text: str, voice: str):
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
        )

        player_thread = threading.Thread(
            target=self._play_pcm,
            args=(process,),
            daemon=True,
        )
        player_thread.start()

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=self.rate,
                volume="+0%",
                pitch=self.pitch,
            )

            async for chunk in communicate.stream():
                if chunk["type"] != "audio":
                    continue

                audio_data = chunk["data"]
                if not audio_data:
                    continue

                try:
                    process.stdin.write(audio_data)
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    break

        finally:
            try:
                process.stdin.close()
            except Exception:
                pass

            process.wait()
            player_thread.join(timeout=5)

            try:
                process.stdout.close()
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

        log.info(f"[TTS] Говорю: {text}")

        for voice in self.voices:
            try:
                asyncio.run(
                    self._speak_async(text, voice)
                )
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
