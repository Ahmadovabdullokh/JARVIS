import subprocess
import time
from pathlib import Path

import pyautogui

from app.tools.common import (
    optional_import,
    powershell,
    resolve_path,
)


def _volume_interface():
    AudioUtilities = optional_import("pycaw.pycaw")
    if AudioUtilities is None:
        return None, None
    try:
        from comtypes import CLSCTX_ALL

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            AudioUtilities.IAudioEndpointVolume._iid_,
            CLSCTX_ALL,
            None,
        )
        return devices, interface.QueryInterface(AudioUtilities.IAudioEndpointVolume)
    except Exception:
        return None, None


def _ffmpeg():
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found
    imageio_ffmpeg = optional_import("imageio_ffmpeg")
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def _ffprobe():
    import shutil

    return shutil.which("ffprobe")


def register(registry):

    @registry.tool(
        "volume_get",
        "Показать текущую громкость.",
        {"type": "object", "properties": {}, "required": []},
        category="media",
    )
    def volume_get():
        _, volume = _volume_interface()
        if volume is None:
            return powershell(
                "(Get-CimInstance -Namespace root/cimv2 -ClassName Win32_SoundDevice "
                "| Select-Object -First 1).Name",
                timeout=15,
            )
        return f"Громкость: {int(round(volume.GetMasterVolumeLevelScalar() * 100))}%"

    @registry.tool(
        "volume_set",
        "Установить громкость от 0 до 100.",
        {
            "type": "object",
            "properties": {"level": {"type": "integer"}},
            "required": ["level"],
        },
        category="media",
    )
    def volume_set(level):
        _, volume = _volume_interface()
        if volume is None:
            for _ in range(50):
                pyautogui.press("volumedown")
            steps = max(0, min(50, int(level or 0) // 2))
            for _ in range(steps):
                pyautogui.press("volumeup")
            return f"Громкость примерно {level}% (через клавиши)."
        value = max(0, min(100, int(level))) / 100.0
        volume.SetMasterVolumeLevelScalar(value, None)
        return f"Громкость: {int(level)}%"

    @registry.tool(
        "volume_mute",
        "Включить или выключить звук.",
        {
            "type": "object",
            "properties": {"muted": {"type": "boolean"}},
            "required": [],
        },
        category="media",
    )
    def volume_mute(muted=None):
        _, volume = _volume_interface()
        if volume is None:
            pyautogui.press("volumemute")
            return "Звук переключён."
        if muted is None:
            muted = not bool(volume.GetMute())
        volume.SetMute(1 if muted else 0, None)
        return "Звук выключен." if muted else "Звук включён."

    @registry.tool(
        "media_key",
        "Управление медиаплеером.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "play_pause",
                        "next",
                        "previous",
                        "stop",
                    ],
                }
            },
            "required": ["action"],
        },
        category="media",
    )
    def media_key(action):
        keys = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "stop": "stop",
        }
        pyautogui.press(keys[action])
        return f"Медиа: {action}."

    @registry.tool(
        "audio_play",
        "Воспроизвести аудиофайл.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="media",
    )
    def audio_play(path):
        target = resolve_path(path, must_exist=True)
        pygame = optional_import("pygame")
        if pygame is not None:
            try:
                pygame.mixer.init()
                pygame.mixer.music.load(str(target))
                pygame.mixer.music.play()
                return f"Воспроизведение: {target}"
            except Exception as error:
                return f"Не удалось воспроизвести: {error}"
        import winsound

        winsound.PlaySound(str(target), winsound.SND_FILENAME)
        return f"Воспроизведение: {target}"

    @registry.tool(
        "audio_beep",
        "Издать системный звуковой сигнал.",
        {
            "type": "object",
            "properties": {
                "frequency": {"type": "integer"},
                "duration": {"type": "integer"},
            },
            "required": [],
        },
        category="media",
    )
    def audio_beep(frequency=800, duration=300):
        import winsound

        winsound.Beep(
            max(37, int(frequency or 800)),
            max(10, int(duration or 300)),
        )
        return "Сигнал воспроизведён."

    @registry.tool(
        "audio_record",
        "Записать звук с микрофона.",
        {
            "type": "object",
            "properties": {
                "duration": {"type": "number"},
                "path": {"type": "string"},
                "rate": {"type": "integer"},
            },
            "required": ["duration"],
        },
        category="media",
    )
    def audio_record(duration=5, path=None, rate=44100):
        sounddevice = optional_import("sounddevice")
        numpy = optional_import("numpy")
        scipy = optional_import("scipy.io.wavfile")
        if sounddevice is None or numpy is None or scipy is None:
            return "Для записи звука установите sounddevice, numpy и scipy."
        seconds = max(0.2, float(duration or 5))
        recording = sounddevice.rec(
            int(seconds * int(rate or 44100)),
            samplerate=int(rate or 44100),
            channels=1,
            dtype="int16",
        )
        sounddevice.wait()
        output = Path(path or f"recording_{int(time.time())}.wav")
        output.parent.mkdir(parents=True, exist_ok=True)
        scipy.write(str(output), int(rate or 44100), recording)
        return f"Аудио записано: {output}"

    @registry.tool(
        "audio_convert",
        "Конвертировать аудио через ffmpeg.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["source", "target"],
        },
        category="media",
    )
    def audio_convert(source, target):
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            return "ffmpeg не найден. Установите ffmpeg."
        source_path = resolve_path(source, must_exist=True)
        target_path = Path(target).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(source_path), str(target_path)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            return result.stderr[-2000:]
        return f"Конвертировано: {target_path}"

    @registry.tool(
        "audio_trim",
        "Обрезать аудио по времени.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "start": {"type": "number"},
                "duration": {"type": "number"},
            },
            "required": ["source", "target", "start", "duration"],
        },
        category="media",
    )
    def audio_trim(source, target, start=0, duration=10):
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            return "ffmpeg не найден. Установите ffmpeg."
        source_path = resolve_path(source, must_exist=True)
        target_path = Path(target).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(start),
                "-t",
                str(duration),
                "-i",
                str(source_path),
                "-c",
                "copy",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            return result.stderr[-2000:]
        return f"Фрагмент сохранён: {target_path}"

    @registry.tool(
        "audio_info",
        "Метаданные аудиофайла.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="media",
    )
    def audio_info(path):
        target = resolve_path(path, must_exist=True)
        mutagen = optional_import("mutagen")
        if mutagen is None:
            return f"Файл: {target} ({target.stat().st_size} байт)"
        try:
            audio = mutagen.File(str(target), easy=True)
            if audio is None:
                return "Метаданные не найдены."
            lines = [f"Файл: {target}"]
            lines.append(f"Длительность: {audio.info.length:.1f} c")
            lines.append(f"Битрейт: {getattr(audio.info, 'bitrate', '?')}")
            for key, value in dict(audio).items():
                lines.append(f"{key}: {value}")
            return "\n".join(lines)
        except Exception as error:
            return f"Не удалось прочитать метаданные: {error}"

    @registry.tool(
        "video_info",
        "Информация о видеофайле.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="media",
    )
    def video_info(path):
        target = resolve_path(path, must_exist=True)
        ffprobe = _ffprobe()
        if ffprobe:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return result.stdout
        cv2 = optional_import("cv2")
        if cv2 is None:
            return f"Файл: {target} ({target.stat().st_size} байт)"
        capture = cv2.VideoCapture(str(target))
        info = (
            f"Кадров: {int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}\n"
            f"FPS: {capture.get(cv2.CAP_PROP_FPS)}\n"
            f"Размер: {int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
        )
        capture.release()
        return info

    @registry.tool(
        "video_convert",
        "Конвертировать видео через ffmpeg.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["source", "target"],
        },
        category="media",
    )
    def video_convert(source, target):
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            return "ffmpeg не найден. Установите ffmpeg."
        source_path = resolve_path(source, must_exist=True)
        target_path = Path(target).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(source_path), str(target_path)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            return result.stderr[-2000:]
        return f"Видео конвертировано: {target_path}"

    @registry.tool(
        "video_extract_audio",
        "Извлечь звук из видео.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["source", "target"],
        },
        category="media",
    )
    def video_extract_audio(source, target):
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            return "ffmpeg не найден. Установите ffmpeg."
        source_path = resolve_path(source, must_exist=True)
        target_path = Path(target).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-acodec",
                "copy",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            return result.stderr[-2000:]
        return f"Аудио извлечено: {target_path}"

    @registry.tool(
        "video_thumbnail",
        "Сохранить кадр из видео.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "time": {"type": "number"},
            },
            "required": ["source"],
        },
        category="media",
    )
    def video_thumbnail(source, target=None, time=0):
        ffmpeg = _ffmpeg()
        source_path = resolve_path(source, must_exist=True)
        target_path = Path(
            target or f"thumbnail_{int(time.time())}.png"
        ).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not ffmpeg:
            return "ffmpeg не найден. Установите ffmpeg."
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(time),
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return result.stderr[-2000:]
        return f"Кадр сохранён: {target_path}"
