import io
import queue
import threading
import time
import wave

import numpy as np
import sounddevice as sd

from app.logging import get_logger

log = get_logger(__name__)


class VoiceListener:

    def __init__(
        self,
        api_key,
        sample_rate=16000,
        silence_threshold=0.005,
        min_speech_seconds=0.25,
        max_speech_seconds=12.0,
        silence_duration=0.7,
        initial_silence_seconds=1.2,
        noise_adapt_k=3.0,
        noise_max_ratio=8.0,
        language="ru",
        model="whisper-large-v3",
        prompt="",
        local_model="",
        local_device="cpu",
        local_compute_type="int8",
    ):
        self.local_model_name = str(local_model or "").strip()
        self.enabled = bool(api_key or self.local_model_name)
        # Временное выключение пользователем (шумная комната) не путать
        # с enabled — доступностью STT-бэкенда.
        self.mic_disabled = False
        if not self.enabled:
            log.info(
                "[STT] Голосовой ввод отключён: нет GROQ_API_KEY "
                "и локальной STT-модели."
            )

        self.sample_rate = sample_rate
        self.silence_threshold = max(1e-5, float(silence_threshold or 0.005))
        self.min_speech_seconds = min_speech_seconds
        self.max_speech_seconds = max_speech_seconds
        self.silence_duration = silence_duration
        self.initial_silence_seconds = initial_silence_seconds
        self.noise_adapt_k = max(1.5, float(noise_adapt_k or 3.0))
        self.noise_max_ratio = max(2.0, float(noise_max_ratio or 8.0))
        self.language = str(language or "ru").strip().lower() or "ru"
        self.noise_floor = 0.0
        self.model = model
        self.prompt = str(prompt or "").strip()

        self.client = None
        if api_key:
            try:
                # groq — ~0.4 с импорта; грузим только при наличии ключа.
                from groq import Groq

                self.client = Groq(api_key=api_key)
            except Exception as error:
                log.info(f"[STT] Groq недоступен: {error}")
        self.local_model = None
        self._prompt_supported = True

        # Постоянный поток-индикатор: раньше measure_level() открывал
        # и закрывал sd.InputStream по 3-4 раза в секунду, что на
        # Windows дёргало WASAPI и жгло CPU.
        self._meter_lock = threading.RLock()
        self._meter_stream = None
        self._meter_level = 0.0
        self._meter_at = 0.0

        if self.local_model_name:
            try:
                from faster_whisper import WhisperModel

                self.local_model = WhisperModel(
                    self.local_model_name,
                    device=str(local_device or "cpu"),
                    compute_type=str(local_compute_type or "int8"),
                )
                log.info(f"[STT] Локальная модель: {self.local_model_name}")
            except Exception as error:
                log.info(f"[STT] Локальная модель недоступна: {error}")

        # Включаемся только если реально есть рабочий бэкенд.
        self.enabled = self.client is not None or self.local_model is not None
        if not self.enabled:
            log.info(
                "[STT] Голосовой ввод отключён: локальная модель "
                "не загрузилась и GROQ_API_KEY отсутствует."
            )

        if self.client is not None:
            log.info("[GROQ] Speech-to-Text")
            log.info(f"[GROQ] Модель: {self.model}")
            log.info("[GROQ] Клиент готов.")
        else:
            log.info("[STT] Используется только локальная модель.")

    # =====================================================
    # NUMPY -> WAV
    # =====================================================

    def _make_wav(self, audio):

        audio = np.asarray(
            audio,
            dtype=np.float32
        )

        audio = np.clip(
            audio,
            -1.0,
            1.0
        )

        audio_int16 = (
            audio * 32767
        ).astype(np.int16)

        buffer = io.BytesIO()

        with wave.open(
            buffer,
            "wb"
        ) as wav:

            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(
                self.sample_rate
            )

            wav.writeframes(
                audio_int16.tobytes()
            )

        buffer.seek(0)

        return buffer

    # =====================================================
    # RECORD
    # =====================================================

    def threshold_for(self, noise_floor):
        adaptive = self.noise_adapt_k * float(noise_floor or 0.0)
        return min(
            max(self.silence_threshold, adaptive),
            self.silence_threshold * self.noise_max_ratio,
        )

    def _record_audio(self):

        audio_queue = queue.Queue()

        def callback(
            indata,
            frames,
            time_info,
            status
        ):

            if status:
                log.info(
                    f"[AUDIO] {status}"
                )

            audio_queue.put(
                indata.copy()
            )

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=800,
            callback=callback
        )

        chunks = []

        speech_started = False
        silence_started = None

        # -------------------------------------------------
        # АДАПТИВНЫЙ ПОРОГ: отслеживаем собственный шум микрофона
        # -------------------------------------------------

        noise_floor = self.noise_floor

        def current_threshold():
            return self.threshold_for(noise_floor)

        self._record_threshold = current_threshold()

        start_time = time.monotonic()

        log.info("[MIC] Слушаю...")

        stream.start()

        try:

            while True:

                chunk = audio_queue.get()

                if self.mic_disabled:
                    break

                audio = np.squeeze(
                    chunk
                )

                chunks.append(audio)

                now = time.monotonic()

                elapsed = (
                    now - start_time
                )

                if elapsed >= self.max_speech_seconds:
                    break

                # -----------------------------------------
                # НЕТ РЕЧИ — БЫСТРО ВЕРНУТЬСЯ К ПРОСЛУШИВАНИЮ
                # -----------------------------------------

                if (
                    not speech_started
                    and elapsed >= self.initial_silence_seconds
                ):
                    break

                # -----------------------------------------
                # ЭНЕРГИЯ ТЕКУЩЕГО КУСКА
                # -----------------------------------------

                energy = float(
                    np.sqrt(
                        np.mean(
                            audio ** 2
                        )
                    )
                )

                threshold = current_threshold()

                # -----------------------------------------
                # ФОН В ТИШИНЕ: ОБНОВЛЯЕМ ОЦЕНКУ ШУМА
                # -----------------------------------------

                if energy < threshold and not speech_started:
                    noise_floor = (
                        0.85 * noise_floor
                        + 0.15 * energy
                    )
                    continue

                # -----------------------------------------
                # НАЧАЛО РЕЧИ
                # -----------------------------------------

                if energy >= threshold:

                    speech_started = True
                    silence_started = None

                    continue

                # -----------------------------------------
                # ТИШИНА ПОСЛЕ РЕЧИ
                # -----------------------------------------

                if speech_started:

                    if silence_started is None:
                        silence_started = now

                    silence_time = (
                        now - silence_started
                    )

                    if (
                        silence_time
                        >= self.silence_duration
                        and elapsed
                        >= self.min_speech_seconds
                    ):
                        break

        finally:

            stream.stop()
            stream.close()

        self.noise_floor = noise_floor
        self._record_threshold = current_threshold()

        if not chunks:
            return None

        audio = np.concatenate(
            chunks
        )

        return audio

    # =====================================================
    # TRANSCRIBE
    # =====================================================

    def _create_transcription(self, wav_data, use_prompt):
        params = {
            "file": ("jarvis.wav", wav_data),
            "model": self.model,
            "language": self.language,
            "response_format": "json",
            "temperature": 0.0,
        }

        if use_prompt and self.prompt and self._prompt_supported:
            params["prompt"] = self.prompt

        return (
            self.client
            .audio
            .transcriptions
            .create(**params)
        )

    def _transcribe_local(self, audio):
        segments, _ = self.local_model.transcribe(
            audio.astype("float32"),
            language=self.language,
            vad_filter=True,
        )
        return " ".join(
            str(segment.text or "").strip()
            for segment in segments
            if str(segment.text or "").strip()
        ).strip()

    def _transcribe(self, audio):

        if self.local_model is not None:
            try:
                log.info("[STT] Распознаю локально...")
                result = self._transcribe_local(audio)
                log.info(f"[STT] Результат: {result}")
                return result
            except Exception as error:
                log.info(f"[STT] Локальное распознавание не удалось: {error}")
                if self.client is None:
                    return ""

        if self.client is None:
            return ""

        log.info("[GROQ] Распознаю...")

        try:

            wav_file = self._make_wav(
                audio
            )

            wav_data = wav_file.read()

            try:
                transcription = self._create_transcription(
                    wav_data,
                    use_prompt=True,
                )
            except Exception as prompt_error:
                if not self.prompt:
                    raise

                # Провайдер не поддерживает prompt для этой модели:
                # запоминаем и больше не отправляем его.
                self._prompt_supported = False
                log.info(
                    f"[GROQ] Подсказка STT не поддерживается, "
                    f"повтор без неё: {prompt_error}"
                )
                transcription = self._create_transcription(
                    wav_data,
                    use_prompt=False,
                )

            result = (
                transcription.text
                or ""
            ).strip()

            log.info(
                f"[GROQ] Результат: {result}"
            )

            return result

        except Exception as e:

            log.info(
                f"[GROQ ERROR] {e}"
            )

            return ""

    # =====================================================
    # PUBLIC
    # =====================================================

    def listen_once(self):

        if not self.enabled or self.mic_disabled:
            return ""

        try:

            audio = self._record_audio()

            if audio is None or self.mic_disabled:
                return ""

            energy = float(
                np.sqrt(
                    np.mean(
                        audio ** 2
                    )
                )
            )

            if energy < self.silence_threshold:
                return ""

            return self._transcribe(
                audio
            )

        except Exception as e:

            log.info(
                f"[LISTENER ERROR] {e}"
            )

            return ""

    def _meter_callback(self, indata, frames, time_info, status):
        try:
            block = np.squeeze(
                np.asarray(indata, dtype=np.float32)
            )
            self._meter_level = float(
                np.sqrt(np.mean(block ** 2))
            )
            self._meter_at = time.monotonic()
        except Exception:
            pass

    def _meter_is_active(self, stream):
        try:
            return bool(stream.active)
        except Exception:
            return False

    def _ensure_meter_stream(self):
        """Открывает поток-индикатор один раз и переиспользует его."""

        stream = self._meter_stream
        if stream is not None:
            if self._meter_is_active(stream):
                return stream
            self.close_meter()

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=800,
            callback=self._meter_callback,
        )
        stream.start()
        self._meter_stream = stream
        return stream

    def close_meter(self):
        """Закрывает поток-индикатор (выключение микрофона, выход)."""

        with self._meter_lock:
            stream = self._meter_stream
            self._meter_stream = None
        if stream is None:
            return
        for method in ("stop", "close"):
            try:
                getattr(stream, method)()
            except Exception:
                pass

    def measure_level(self, seconds=0.3):
        """Громкость микрофона для индикатора UI (последний блок).

        `seconds` оставлен для совместимости: раньше метод открывал
        поток и читал несколько блоков, теперь уровень приходит из
        постоянного потока.
        """

        if not self.enabled or self.mic_disabled:
            return 0.0

        try:
            with self._meter_lock:
                stream = self._ensure_meter_stream()
        except Exception:
            self.close_meter()
            return 0.0

        if stream is None:
            return 0.0

        if time.monotonic() - self._meter_at > 0.5:
            # Колбэк ещё не успел получить первый блок.
            time.sleep(0.05)

        return float(self._meter_level)