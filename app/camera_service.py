"""Захват кадров с камеры и общий буфер для жестов и MJPEG-стрима.

Сервис умеет работать с локальной камерой (OpenCV index) и с сетевым
MJPEG/HTTP-потоком (например, IP Webcam на телефоне). Камера
открывается только пока включён режим камеры; остальные подсистемы
получают уже готовые кадры и не открывают устройство повторно.
"""

import os
import secrets
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from app import config as config_module
from app.logging import get_logger

log = get_logger(__name__)

QUALITY_PRESETS = {
    "performance": {
        "stream_fps": 12.0,
        "jpeg_quality": 74,
        "sharpness": 0.2,
    },
    "balanced": {
        "stream_fps": 20.0,
        "jpeg_quality": 82,
        "sharpness": 0.35,
    },
    "quality": {
        "stream_fps": 30.0,
        "jpeg_quality": 88,
        "sharpness": 0.5,
    },
}

DEFAULT_SETTINGS = {
    "enabled": False,
    "source": "pc",
    "index": 0,
    "url": "",
    "width": 640,
    "height": 480,
    "fps": 30,
    "stream_fps": 30,
    "analyze_fps": 12,
    "jpeg_quality": 88,
    "mirror": True,
    "reconnect_delay": 2.0,
    "max_clients": 4,
    "backend": "auto",
    "fourcc": "MJPG",
    "quality": "quality",
    "sharpness": 0.5,
    "upscale": False,
    "background": True,
    "immersive": True,
    "fit": "cover",
    "phone_timeout": 5.0,
    "phone_auto_switch": True,
}

SOURCES = ("pc", "network", "phone")
BACKENDS = ("auto", "msmf", "dshow", "any")
QUALITY_NAMES = tuple(QUALITY_PRESETS) + ("custom",)
FIT_MODES = ("cover", "contain")


def _backend_candidates(name):
    """Возвращает список (имя, cv2 backend) с учётом платформы."""

    import cv2

    requested = str(name or "auto").strip().lower()
    mapping = {
        "msmf": cv2.CAP_MSMF,
        "dshow": cv2.CAP_DSHOW,
        "any": cv2.CAP_ANY,
    }
    if requested in mapping:
        return [(requested, mapping[requested])]
    if os.name == "nt":
        return [
            ("msmf", cv2.CAP_MSMF),
            ("dshow", cv2.CAP_DSHOW),
            ("any", cv2.CAP_ANY),
        ]
    return [("any", cv2.CAP_ANY)]


def _apply_quality_preset(settings):
    """Применяет пресет к стриму, не меняя разрешение захвата."""

    name = str(settings.get("quality") or "quality").strip().lower()
    if name not in QUALITY_PRESETS:
        settings["quality"] = "custom"
        return settings
    settings["quality"] = name
    settings.update(QUALITY_PRESETS[name])
    return settings


def _mask_url(url):
    """Скрывает логин/пароль в URL перед показом в UI и логах."""

    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit(
            (parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment)
        )
    return text


def _as_int(value, default, minimum=0, maximum=10000):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _as_float(value, default, minimum=0.1, maximum=240.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def load_camera_settings():
    """Читает секцию camera из config.json и дополняет значениями по умолчанию."""

    try:
        config = config_module.read_config_file() or {}
    except Exception:
        config = {}
    raw = config.get("camera")
    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({key: value for key, value in raw.items() if key in settings})
    settings = _normalize_settings(settings)
    settings["enabled"] = bool(settings.get("enabled", False))
    return settings


def _normalize_settings(settings):
    settings = _apply_quality_preset(settings)
    source = str(settings.get("source") or "pc").strip().lower()
    settings["source"] = source if source in SOURCES else "pc"
    backend = str(settings.get("backend") or "auto").strip().lower()
    settings["backend"] = backend if backend in BACKENDS else "auto"
    fourcc = str(settings.get("fourcc") or "MJPG").strip().upper()
    settings["fourcc"] = fourcc[:4]
    quality = str(settings.get("quality") or "quality").strip().lower()
    settings["quality"] = quality if quality in QUALITY_NAMES else "quality"
    fit = str(settings.get("fit") or "cover").strip().lower()
    settings["fit"] = fit if fit in FIT_MODES else "cover"
    settings["index"] = _as_int(settings.get("index"), 0, 0, 32)
    settings["width"] = _as_int(settings.get("width"), 640, 160, 3840)
    settings["height"] = _as_int(settings.get("height"), 480, 120, 2160)
    settings["fps"] = _as_float(settings.get("fps"), 30.0, 1.0, 120.0)
    settings["stream_fps"] = _as_float(
        settings.get("stream_fps"), 30.0, 1.0, 60.0
    )
    settings["analyze_fps"] = _as_float(
        settings.get("analyze_fps"), 12.0, 1.0, 60.0
    )
    settings["jpeg_quality"] = _as_int(
        settings.get("jpeg_quality"), 88, 30, 95
    )
    settings["sharpness"] = _as_float(
        settings.get("sharpness"), 0.5, 0.0, 1.5
    )
    settings["max_clients"] = _as_int(
        settings.get("max_clients"), 4, 1, 16
    )
    settings["mirror"] = bool(settings.get("mirror", True))
    settings["upscale"] = bool(settings.get("upscale", False))
    settings["background"] = bool(settings.get("background", True))
    settings["immersive"] = bool(settings.get("immersive", True))
    settings["url"] = str(settings.get("url") or "").strip()
    settings["reconnect_delay"] = _as_float(
        settings.get("reconnect_delay"), 2.0, 0.2, 30.0
    )
    settings["phone_timeout"] = _as_float(
        settings.get("phone_timeout"), 5.0, 1.0, 60.0
    )
    settings["phone_auto_switch"] = bool(
        settings.get("phone_auto_switch", True)
    )
    return settings


def probe_cameras(
    indices=(0, 1, 2, 3),
    width=640,
    height=480,
    fps=30,
    backend="auto",
    samples=6,
):
    """Проверяет камеры ПК и возвращает реальные параметры источников.

    Виртуальные камеры часто открываются, но отдают почти чёрный кадр;
    такие источники помечаются ``blank=True`` и в UI не рекомендуются.
    """

    import cv2

    results = []
    for index in indices:
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if index < 0:
            continue
        for name, backend_id in _backend_candidates(backend):
            capture = cv2.VideoCapture(index, backend_id)
            if not capture.isOpened():
                capture.release()
                continue
            try:
                capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                capture.set(cv2.CAP_PROP_FPS, fps)
                frames = []
                started = time.monotonic()
                for _ in range(max(1, int(samples))):
                    ok, frame = capture.read()
                    if ok and frame is not None:
                        frames.append(frame)
                elapsed = max(0.001, time.monotonic() - started)
            finally:
                actual_width = int(
                    capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0
                )
                actual_height = int(
                    capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
                )
                capture_fps = round(
                    float(capture.get(cv2.CAP_PROP_FPS) or 0), 1
                )
                capture.release()
            if not frames:
                continue
            last = frames[-1]
            try:
                mean, deviation = cv2.meanStdDev(last)
                brightness = round(float(mean.mean()), 1)
                contrast = round(float(deviation.mean()), 1)
            except Exception:
                brightness = 0.0
                contrast = 0.0
            results.append(
                {
                    "index": index,
                    "backend": name,
                    "width": actual_width,
                    "height": actual_height,
                    "capture_fps": capture_fps,
                    "measured_fps": round(len(frames) / elapsed, 1),
                    "brightness": brightness,
                    "contrast": contrast,
                    "blank": brightness < 10.0 and contrast < 24.0,
                }
            )
            break
    return results


class CameraService:
    """Один поток захвата + последний кадр/JPEG для всех потребителей."""

    def __init__(self):
        self._lock = threading.RLock()
        self._frame_lock = threading.Lock()
        self._listeners_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._listeners = []
        self._settings = dict(DEFAULT_SETTINGS)
        self._latest_frame = None
        self._latest_frame_at = 0.0
        self._raw_jpeg = b""
        self._raw_jpeg_at = 0.0
        self._overlay_jpeg = b""
        self._overlay_jpeg_at = 0.0
        self._fps = 0.0
        self._frame_count = 0
        self._fps_mark = time.monotonic()
        self._error = ""
        self._running = False
        self._actual_width = 0
        self._actual_height = 0
        self._actual_backend = ""
        self._capture_fps = 0.0
        self._started_at = 0.0
        self._clients = 0
        self._client_lock = threading.Lock()
        self._external_at = 0.0
        self._external_device = ""
        self._external_frames = 0
        self._phone_state = "idle"
        self.stream_token = secrets.token_urlsafe(24)

    # ------------------------------------------------------------------
    # Управление
    # ------------------------------------------------------------------

    def start(self, settings=None):
        with self._lock:
            candidate = dict(self._settings)
            if isinstance(settings, dict):
                candidate.update(settings)
            candidate = self._normalize(candidate)
            if self._running:
                if candidate == self._settings:
                    return self.status()
                self._stop_locked()
            self._settings = candidate
            self._stop.clear()
            self._error = ""
            self._frame_count = 0
            self._fps = 0.0
            self._fps_mark = time.monotonic()
            self._started_at = time.time()
            self._actual_backend = ""
            self._capture_fps = 0.0
            self._external_at = 0.0
            self._external_device = ""
            self._external_frames = 0
            self._phone_state = "idle"
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="JARVIS-Camera",
                daemon=True,
            )
            self._running = True
            self._thread.start()
        log.info(
            "[CAMERA] Запуск: source=%s index=%s url=%s",
            self._settings.get("source"),
            self._settings.get("index"),
            _mask_url(self._settings.get("url")),
        )
        return self.status()

    def stop(self):
        with self._lock:
            self._stop_locked()
        log.info("[CAMERA] Остановлена.")

    def _stop_locked(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        self._running = False
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        with self._frame_lock:
            self._latest_frame = None
            self._raw_jpeg = b""
            self._overlay_jpeg = b""
            self._latest_frame_at = 0.0
            self._raw_jpeg_at = 0.0
            self._overlay_jpeg_at = 0.0
        with self._lock:
            self._external_at = 0.0
            self._external_device = ""
            self._external_frames = 0
            self._phone_state = "idle"

    def restart(self, settings=None):
        self.stop()
        return self.start(settings)

    def _normalize(self, settings):
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in settings.items() if k in merged})
        merged = _normalize_settings(merged)
        merged["enabled"] = True
        return merged

    def set_quality(self, quality):
        """Меняет пресет качества на лету, перезапуская захват."""

        settings = dict(self._settings)
        settings["quality"] = quality
        if self._running:
            return self.restart(settings)
        with self._lock:
            self._settings = self._normalize(settings)
            self._settings["enabled"] = bool(settings.get("enabled", False))
        return self.status()

    def update_settings(self, updates):
        """Обновляет нечувствительные к захвату настройки без рестарта."""

        with self._lock:
            merged = dict(self._settings)
            merged.update(updates if isinstance(updates, dict) else {})
            self._settings = self._normalize(merged)
            self._settings["enabled"] = bool(merged.get("enabled", False))
        return self.status()

    # ------------------------------------------------------------------
    # Поток захвата
    # ------------------------------------------------------------------

    def _open_capture(self):
        import cv2

        source = self._settings.get("source")
        if source == "network":
            url = self._settings.get("url") or ""
            if not url:
                raise RuntimeError("Не задан URL сетевой камеры.")
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if not capture.isOpened():
                capture.release()
                capture = cv2.VideoCapture(url)
            return capture

        index = int(self._settings.get("index") or 0)
        errors = []
        for name, backend in _backend_candidates(
            self._settings.get("backend")
        ):
            capture = cv2.VideoCapture(index, backend)
            if capture.isOpened():
                self._actual_backend = name
                self._configure_capture(capture)
                return capture
            capture.release()
            errors.append(name)
        raise RuntimeError(
            f"Камера с индексом {index} не открылась "
            f"(backend: {', '.join(errors)}). "
            "Проверьте подключение и права доступа Windows."
        )

    def _configure_capture(self, capture):
        """Настраивает формат MJPG и размер до первого чтения кадра."""

        import cv2

        if self._settings.get("source") != "pc":
            return
        fourcc = str(self._settings.get("fourcc") or "").strip().upper()
        if fourcc and len(fourcc) == 4:
            try:
                capture.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*fourcc),
                )
            except Exception:
                pass
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings["width"])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings["height"])
        capture.set(cv2.CAP_PROP_FPS, self._settings["fps"])
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def _capture_loop(self):
        if self._settings.get("source") == "phone":
            self._phone_loop()
            return

        import cv2

        capture = None
        failures = 0
        stream_interval = 1.0 / max(1.0, float(self._settings["stream_fps"]))
        analyze_interval = 1.0 / max(
            1.0, float(self._settings["analyze_fps"])
        )
        last_stream = 0.0
        last_analyze = 0.0
        try:
            while not self._stop.is_set():
                if capture is None:
                    try:
                        capture = self._open_capture()
                        self._actual_width = int(
                            capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0
                        )
                        self._actual_height = int(
                            capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
                        )
                        self._capture_fps = round(
                            float(capture.get(cv2.CAP_PROP_FPS) or 0), 1
                        )
                        if self._actual_width <= 0 or self._actual_height <= 0:
                            self._actual_width = 0
                            self._actual_height = 0
                        failures = 0
                        self._error = ""
                        log.info(
                            "[CAMERA] Источник открыт: %sx%s @ %s fps "
                            "(backend=%s, fourcc=%s)",
                            self._actual_width or "?",
                            self._actual_height or "?",
                            self._capture_fps or "?",
                            self._actual_backend or self._settings.get("backend"),
                            self._settings.get("fourcc"),
                        )
                    except Exception as error:
                        self._error = str(error)
                        log.info(
                            "[CAMERA] Не удалось открыть камеру: %s", error
                        )
                        if self._stop.wait(self._settings["reconnect_delay"]):
                            break
                        continue

                ok, frame = capture.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 12:
                        self._error = (
                            "Нет кадров с камеры. Проверьте подключение "
                            "и URL."
                        )
                        log.info("[CAMERA] Поток кадров потерян, перезапуск.")
                        try:
                            capture.release()
                        except Exception:
                            pass
                        capture = None
                        failures = 0
                        if self._stop.wait(self._settings["reconnect_delay"]):
                            break
                    else:
                        time.sleep(0.05)
                    continue

                failures = 0
                self._error = ""
                now = time.monotonic()
                if self._settings.get("mirror"):
                    frame = cv2.flip(frame, 1)
                self._actual_height, self._actual_width = frame.shape[:2]
                with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_frame_at = time.time()

                if now - last_stream >= stream_interval:
                    last_stream = now
                    jpeg = self._encode_jpeg(frame)
                    if jpeg:
                        with self._frame_lock:
                            self._raw_jpeg = jpeg
                            self._raw_jpeg_at = time.time()

                if now - last_analyze >= analyze_interval:
                    last_analyze = now
                    self._notify(frame.copy())

                self._frame_count += 1
                elapsed = now - self._fps_mark
                if elapsed >= 1.0:
                    self._fps = round(self._frame_count / elapsed, 1)
                    self._frame_count = 0
                    self._fps_mark = now
        except Exception as error:
            self._error = f"{type(error).__name__}: {error}"
            log.info("[CAMERA] Критическая ошибка: %s", self._error)
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            self._running = False
            if self._thread is threading.current_thread():
                self._thread = None
            log.info("[CAMERA] Поток захвата завершён.")

    def _phone_loop(self):
        """Ждёт кадры от приложения на телефоне, не открывая устройство."""

        timeout = float(self._settings.get("phone_timeout") or 5.0)
        state = "idle"
        last_frames = 0
        last_mark = time.monotonic()
        log.info("[CAMERA] Источник «телефон»: ждём кадры от приложения.")
        while not self._stop.is_set():
            now = time.monotonic()
            with self._frame_lock:
                external_at = self._external_at
                frames = self._external_frames
                width = self._actual_width
                height = self._actual_height
            age = time.time() - external_at if external_at else None
            if age is not None and age <= timeout:
                new_state = "live"
            elif external_at:
                new_state = "stale"
            else:
                new_state = "idle"
            if new_state != state:
                state = new_state
                if state == "live":
                    log.info(
                        "[CAMERA] Телефон на связи: %sx%s.",
                        width or "?",
                        height or "?",
                    )
                elif state == "stale":
                    log.info("[CAMERA] Кадры с телефона пропали.")
                else:
                    log.info("[CAMERA] Ждём подключения телефона.")
            self._error = (
                "Телефон не присылает кадры." if state == "stale" else ""
            )
            self._phone_state = state
            elapsed = now - last_mark
            if elapsed >= 1.0:
                delta = max(0, frames - last_frames)
                self._fps = round(delta / elapsed, 1)
                last_frames = frames
                last_mark = now
            self._stop.wait(0.5)

    def _sharpen(self, frame):
        import cv2

        amount = float(self._settings.get("sharpness") or 0.0)
        if amount <= 0.01:
            return frame
        amount = min(1.5, amount)
        try:
            blurred = cv2.GaussianBlur(frame, (0, 0), 1.0)
            return cv2.addWeighted(
                frame,
                1.0 + amount,
                blurred,
                -amount,
                0,
            )
        except Exception:
            return frame

    def _encode_jpeg(self, frame):
        import cv2

        try:
            sharpened = self._sharpen(frame)
            ok, buffer = cv2.imencode(
                ".jpg",
                sharpened,
                [cv2.IMWRITE_JPEG_QUALITY, self._settings["jpeg_quality"]],
            )
            if ok:
                return buffer.tobytes()
        except Exception as error:
            self._error = f"JPEG: {error}"
        return b""

    def encode_jpeg(self, frame):
        """Кодирует кадр с учётом качества и резкости (для overlay)."""

        return self._encode_jpeg(frame)

    # ------------------------------------------------------------------
    # Потребители
    # ------------------------------------------------------------------

    def subscribe(self, callback):
        if not callable(callback):
            return
        with self._listeners_lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback):
        with self._listeners_lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify(self, frame):
        with self._listeners_lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(frame)
            except Exception as error:
                log.info(
                    "[CAMERA] Ошибка обработчика кадра: %s: %s",
                    type(error).__name__,
                    error,
                )

    def publish_overlay(self, jpeg, when=None):
        """Публикует кадр с наложенными landmarks для MJPEG-стрима."""

        if not jpeg:
            return
        with self._frame_lock:
            self._overlay_jpeg = bytes(jpeg)
            self._overlay_jpeg_at = float(when or time.time())

    def submit_external_jpeg(self, jpeg, rotate=0, device=""):
        """Принимает кадр от телефона/браузера и отдаёт его жестам.

        Возвращает пустую строку при успехе или код ошибки:
        ``bad jpeg``, ``camera is off``, ``not phone source``.
        ``rotate`` — угол по часовой стрелке, который нужно применить,
        чтобы кадр стал вертикальным.
        """

        if not jpeg:
            return "bad jpeg"
        if not self.is_running():
            return "camera is off"
        if self._settings.get("source") != "phone":
            return "not phone source"

        import cv2
        import numpy as np

        try:
            array = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
        except Exception:
            frame = None
        if frame is None:
            return "bad jpeg"

        try:
            angle = int(rotate) % 360
        except (TypeError, ValueError):
            angle = 0
        if angle not in (90, 180, 270):
            angle = 0
        if angle == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif angle == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        mirrored = bool(self._settings.get("mirror"))
        if mirrored:
            frame = cv2.flip(frame, 1)

        encoded = b""
        if angle or mirrored:
            encoded = self._encode_jpeg(frame)

        height, width = frame.shape[:2]
        now = time.time()
        with self._frame_lock:
            self._latest_frame = frame
            self._latest_frame_at = now
            self._raw_jpeg = encoded or bytes(jpeg)
            self._raw_jpeg_at = now
            self._actual_width = int(width)
            self._actual_height = int(height)
            self._external_at = now
            self._external_frames += 1
            if device:
                self._external_device = str(device).strip()[:64]
        self._notify(frame.copy())
        return ""

    # ------------------------------------------------------------------
    # Чтение состояния
    # ------------------------------------------------------------------

    def latest_frame(self):
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def _phone_frames_fresh(self):
        """True/False для источника «телефон», None для остальных."""

        if self._settings.get("source") != "phone":
            return None
        external_at = self._external_at
        if not external_at:
            return False
        timeout = float(self._settings.get("phone_timeout") or 5.0)
        return time.time() - external_at <= timeout

    def latest_jpeg(self):
        now = time.time()
        if self._phone_frames_fresh() is False:
            return b""
        with self._frame_lock:
            if (
                self._overlay_jpeg
                and now - self._overlay_jpeg_at < 2.0
            ):
                return self._overlay_jpeg
            if self._raw_jpeg:
                return self._raw_jpeg
        return b""

    def snapshot_jpeg(self):
        jpeg = self.latest_jpeg()
        if jpeg:
            return jpeg
        if self._phone_frames_fresh() is False:
            # Не отдаём vision/снимкам последний устаревший кадр.
            return b""
        frame = self.latest_frame()
        if frame is None:
            return b""
        return self._encode_jpeg(frame)

    def acquire_client(self):
        limit = int(self._settings.get("max_clients") or 4)
        with self._client_lock:
            if self._clients >= limit:
                return False
            self._clients += 1
            return True

    def release_client(self):
        with self._client_lock:
            self._clients = max(0, self._clients - 1)

    def is_running(self):
        with self._lock:
            return self._running

    @property
    def settings(self):
        with self._lock:
            return dict(self._settings)

    def status(self):
        with self._lock:
            running = self._running
            settings = dict(self._settings)
        with self._frame_lock:
            last_frame = self._latest_frame_at
            width = self._actual_width
            height = self._actual_height
        return {
            "enabled": bool(settings.get("enabled")),
            "running": running,
            "source": settings.get("source", "pc"),
            "index": settings.get("index", 0),
            "url": _mask_url(settings.get("url")),
            "width": width,
            "height": height,
            "fps": self._fps,
            "capture_fps": self._capture_fps,
            "requested_fps": settings.get("fps", 30),
            "stream_fps": settings.get("stream_fps", 30),
            "analyze_fps": settings.get("analyze_fps", 12),
            "jpeg_quality": settings.get("jpeg_quality", 88),
            "backend": self._actual_backend
            or settings.get("backend", "auto"),
            "fourcc": settings.get("fourcc", "MJPG"),
            "quality": settings.get("quality", "quality"),
            "sharpness": settings.get("sharpness", 0.5),
            "upscale": bool(settings.get("upscale", False)),
            "background": bool(settings.get("background", True)),
            "immersive": bool(settings.get("immersive", True)),
            "fit": settings.get("fit", "cover"),
            "mirror": bool(settings.get("mirror", True)),
            "phone_state": self._phone_state,
            "phone_device": self._external_device,
            "phone_frames": self._external_frames,
            "phone_timeout": settings.get("phone_timeout", 5.0),
            "phone_auto_switch": bool(
                settings.get("phone_auto_switch", True)
            ),
            "error": self._error,
            "clients": self._clients,
            "last_frame_age": (
                round(time.time() - last_frame, 2) if last_frame else None
            ),
            "uptime_seconds": (
                round(time.time() - self._started_at, 1)
                if self._started_at
                else 0
            ),
        }


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def get_camera_service():
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = CameraService()
        return _SERVICE
