"""Распознавание жестов рук и выполнение действий JARVIS.

MediaPipe HandLandmarker работает локально на кадрах CameraService.
Жест проходит через фильтр стабильности и cooldown, после чего
превращается либо в команду для JARVIS, либо в локальное действие
(громкость, микрофон, скриншот и т.п.).
"""

import math
import queue
import sys
import threading
import time
from collections import deque

from app import config as config_module
from app import performance
from app.camera_service import get_camera_service
from app.logging import get_logger
from app.paths import BASE_DIR, DATA_DIR, MODELS_DIR, resource_path

log = get_logger(__name__)


def _stub_matplotlib():
    """Обходит лишний импорт matplotlib внутри mediapipe.

    ``mediapipe.tasks.python.vision`` подтягивает drawing_utils, а тот
    импортирует matplotlib ради plot_landmarks — функции, которая
    жестам не нужна. Без пакета подставляем пустые модули, чтобы не
    тянуть ~50 МБ в venv и сборку.
    """

    if "matplotlib" in sys.modules:
        return
    try:
        import matplotlib  # noqa: F401
        return
    except ImportError:
        pass
    import types

    matplotlib = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")
    matplotlib.pyplot = pyplot
    sys.modules["matplotlib"] = matplotlib
    sys.modules["matplotlib.pyplot"] = pyplot

DEFAULT_SETTINGS = {
    "enabled": False,
    "num_hands": 1,
    "min_detection_confidence": 0.6,
    "min_tracking_confidence": 0.5,
    "stability_frames": 3,
    "cooldown_ms": 900,
    "speak_actions": True,
    "mirror": True,
    "profile": "media",
    "detection_width": 256,
    "pointer": {
        "enabled": False,
        "smoothing": 0.35,
        "dead_zone": 0.012,
        "click_cooldown_ms": 350,
        "scroll_speed": 3,
        "optical_flow": True,
    },
    "dynamic": {
        "swipe_distance": 0.17,
        "window_ms": 450,
        "circle_min_angle": 300,
        "push_pull_ratio": 0.25,
    },
    "two_hands": {
        "enabled": True,
        "zoom_ratio": 0.12,
        "rotate_degrees": 18,
    },
}

DEFAULT_ACTIONS = {
    "open_palm": {
        "kind": "action",
        "action": "ensure_mic_on",
        "say": "Слушаю.",
    },
    "fist": {"kind": "action", "action": "stop_speaking"},
    "peace": {
        "kind": "action",
        "action": "screenshot",
        "say": "Скриншот сохранён.",
    },
    "thumbs_up": {
        "kind": "action",
        "action": "key",
        "key": "volumeup",
        "say": "Громкость выше.",
    },
    "thumbs_down": {
        "kind": "action",
        "action": "key",
        "key": "volumedown",
        "say": "Громкость ниже.",
    },
    "swipe_left": {
        "kind": "action",
        "action": "key",
        "key": "prevtrack",
        "say": "Предыдущий трек.",
    },
    "swipe_right": {
        "kind": "action",
        "action": "key",
        "key": "nexttrack",
        "say": "Следующий трек.",
    },
    "swipe_up": {
        "kind": "action",
        "action": "key",
        "key": "volumeup",
        "say": "Громкость выше.",
    },
    "swipe_down": {
        "kind": "action",
        "action": "key",
        "key": "volumedown",
        "say": "Громкость ниже.",
    },
    "ok": {
        "kind": "action",
        "action": "key",
        "key": "playpause",
        "say": "",
    },
    "point": {"kind": "none"},
    "pinch": {"kind": "none"},
    "frame": {"kind": "none"},
    "fingers_3": {"kind": "none"},
    "fingers_4": {"kind": "none"},
    "fingers_5": {"kind": "none"},
    "rock": {"kind": "none"},
    "shaka": {"kind": "none"},
    "l_shape": {"kind": "none"},
    "call_me": {"kind": "none"},
    "circle_cw": {"kind": "none"},
    "circle_ccw": {"kind": "none"},
    "push": {"kind": "none"},
    "pull": {"kind": "none"},
    "clap": {"kind": "none"},
    "zoom_in": {"kind": "none"},
    "zoom_out": {"kind": "none"},
    "rotate_cw": {"kind": "none"},
    "rotate_ccw": {"kind": "none"},
}

PROFILE_LABELS = {
    "media": "Медиа",
    "jarvis": "JARVIS",
    "pointer": "Курсор",
    "windows": "Окна и браузер",
    "presentation": "Презентация",
}

_SAFE_VOLUME_UP = {
    "kind": "action",
    "action": "key",
    "key": "volumeup",
    "say": "Громкость выше.",
}
_SAFE_VOLUME_DOWN = {
    "kind": "action",
    "action": "key",
    "key": "volumedown",
    "say": "Громкость ниже.",
}

DEFAULT_PROFILES = {
    "media": DEFAULT_ACTIONS,
    "jarvis": {
        **DEFAULT_ACTIONS,
        "point": {
            "kind": "command",
            "text": "Опиши, что видишь перед камерой.",
        },
        "fingers_3": {
            "kind": "action",
            "action": "set_mode",
            "mode": "chat",
            "say": "Режим чата.",
        },
        "fingers_4": {
            "kind": "action",
            "action": "set_mode",
            "mode": "tasks",
            "say": "Режим задач.",
        },
        "fingers_5": {
            "kind": "action",
            "action": "set_mode",
            "mode": "code",
            "say": "Режим кода.",
        },
    },
    "pointer": {
        "open_palm": {"kind": "pointer", "mode": "release"},
        "fist": {"kind": "pointer", "mode": "pause"},
        "point": {"kind": "pointer", "mode": "move"},
        "pinch": {"kind": "pointer", "mode": "click"},
        "peace": {"kind": "pointer", "mode": "scroll"},
        "ok": {"kind": "pointer", "mode": "enter"},
        "thumbs_up": _SAFE_VOLUME_UP,
        "thumbs_down": _SAFE_VOLUME_DOWN,
    },
    "windows": {
        "swipe_left": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["alt", "left"],
            "say": "Назад.",
        },
        "swipe_right": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["alt", "right"],
            "say": "Вперёд.",
        },
        "thumbs_up": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["alt", "tab"],
            "say": "Переключение окна.",
        },
        "fingers_3": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["ctrl", "tab"],
        },
        "fingers_4": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["ctrl", "shift", "tab"],
        },
        "open_palm": {
            "kind": "action",
            "action": "hotkey",
            "keys": ["alt", "left"],
        },
        "fist": {"kind": "action", "action": "stop_speaking"},
    },
    "presentation": {
        "swipe_left": {
            "kind": "action",
            "action": "key",
            "key": "left",
            "say": "Предыдущий слайд.",
        },
        "swipe_right": {
            "kind": "action",
            "action": "key",
            "key": "right",
            "say": "Следующий слайд.",
        },
        "open_palm": {
            "kind": "action",
            "action": "key",
            "key": "b",
            "say": "Чёрный экран.",
        },
        "peace": {
            "kind": "action",
            "action": "key",
            "key": "p",
            "say": "Указатель.",
        },
        "ok": {
            "kind": "action",
            "action": "key",
            "key": "f5",
            "say": "Старт презентации.",
        },
        "fist": {
            "kind": "action",
            "action": "key",
            "key": "esc",
            "say": "Стоп.",
        },
    },
}

GESTURE_LABELS = {
    "open_palm": "Открытая ладонь",
    "fist": "Кулак",
    "peace": "Victory / два пальца",
    "thumbs_up": "Большой палец вверх",
    "thumbs_down": "Большой палец вниз",
    "swipe_left": "Свайп влево",
    "swipe_right": "Свайп вправо",
    "swipe_up": "Свайп вверх",
    "swipe_down": "Свайп вниз",
    "ok": "OK",
    "point": "Указание",
    "pinch": "Щипок",
    "frame": "Рамка двумя руками",
    "fingers_3": "Три пальца",
    "fingers_4": "Четыре пальца",
    "fingers_5": "Пять пальцев",
    "rock": "Rock",
    "shaka": "Shaka",
    "l_shape": "Буква L",
    "call_me": "Call me",
    "circle_cw": "Круг по часовой",
    "circle_ccw": "Круг против часовой",
    "push": "Толчок к камере",
    "pull": "Отталкивание",
    "clap": "Хлопок",
    "zoom_in": "Приблизить",
    "zoom_out": "Отдалить",
    "rotate_cw": "Поворот вправо",
    "rotate_ccw": "Поворот влево",
}

# cv2.putText не умеет кириллицу без FreeType, поэтому на кадр
# накладываем короткие английские подписи.
GESTURE_LABELS_EN = {
    "open_palm": "OPEN PALM",
    "fist": "FIST",
    "peace": "PEACE",
    "thumbs_up": "THUMB UP",
    "thumbs_down": "THUMB DOWN",
    "swipe_left": "SWIPE LEFT",
    "swipe_right": "SWIPE RIGHT",
    "swipe_up": "SWIPE UP",
    "swipe_down": "SWIPE DOWN",
    "ok": "OK",
    "point": "POINT",
    "pinch": "PINCH",
    "frame": "FRAME",
    "fingers_3": "3 FINGERS",
    "fingers_4": "4 FINGERS",
    "fingers_5": "5 FINGERS",
    "rock": "ROCK",
    "shaka": "SHAKA",
    "l_shape": "L SHAPE",
    "call_me": "CALL ME",
    "circle_cw": "CIRCLE CW",
    "circle_ccw": "CIRCLE CCW",
    "push": "PUSH",
    "pull": "PULL",
    "clap": "CLAP",
    "zoom_in": "ZOOM IN",
    "zoom_out": "ZOOM OUT",
    "rotate_cw": "ROTATE CW",
    "rotate_ccw": "ROTATE CCW",
}

HOLD_FRAMES = {
    "open_palm": 4,
    "point": 6,
    "frame": 5,
    "fist": 2,
    "peace": 2,
    "ok": 2,
    "pinch": 2,
    "thumbs_up": 3,
    "thumbs_down": 3,
    "swipe_left": 1,
    "swipe_right": 1,
    "swipe_up": 1,
    "swipe_down": 1,
    "fingers_5": 3,
    "rock": 3,
    "shaka": 3,
    "l_shape": 3,
    "call_me": 3,
    "circle_cw": 1,
    "circle_ccw": 1,
    "push": 1,
    "pull": 1,
    "clap": 1,
    "zoom_in": 1,
    "zoom_out": 1,
    "rotate_cw": 1,
    "rotate_ccw": 1,
}

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

SWIPE_WINDOW = 0.45
SWIPE_DISTANCE = 0.17


def _as_float(value, default, minimum=0.0, maximum=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _as_int(value, default, minimum=0, maximum=100):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _deep_merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_actions(actions):
    normalized = {}
    if not isinstance(actions, dict):
        return normalized
    for key, value in actions.items():
        name = str(key).strip()
        if not name:
            continue
        if isinstance(value, dict):
            normalized[name] = dict(value)
        elif isinstance(value, str):
            normalized[name] = {"kind": "command", "text": value}
    return normalized


def load_gesture_settings():
    try:
        config = config_module.read_config_file() or {}
    except Exception:
        config = {}
    raw = config.get("gestures")
    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(
        {
            key: value
            for key, value in raw.items()
            if key in settings
            and key not in {"pointer", "dynamic", "two_hands"}
        }
    )
    settings["pointer"] = _deep_merge(
        DEFAULT_SETTINGS["pointer"],
        raw.get("pointer") if isinstance(raw.get("pointer"), dict) else {},
    )
    settings["dynamic"] = _deep_merge(
        DEFAULT_SETTINGS["dynamic"],
        raw.get("dynamic") if isinstance(raw.get("dynamic"), dict) else {},
    )
    settings["two_hands"] = _deep_merge(
        DEFAULT_SETTINGS["two_hands"],
        raw.get("two_hands") if isinstance(raw.get("two_hands"), dict) else {},
    )
    settings["num_hands"] = _as_int(settings.get("num_hands"), 2, 1, 2)
    settings["detection_width"] = _as_int(
        settings.get("detection_width"), 480, 160, 960
    )
    settings["stability_frames"] = _as_int(
        settings.get("stability_frames"), 3, 1, 20
    )
    settings["cooldown_ms"] = _as_int(
        settings.get("cooldown_ms"), 900, 100, 10000
    )
    settings["min_detection_confidence"] = _as_float(
        settings.get("min_detection_confidence"), 0.6, 0.1, 0.99
    )
    settings["min_tracking_confidence"] = _as_float(
        settings.get("min_tracking_confidence"), 0.5, 0.1, 0.99
    )
    settings["speak_actions"] = bool(settings.get("speak_actions", True))
    pointer = settings["pointer"]
    pointer["enabled"] = bool(pointer.get("enabled", False))
    pointer["smoothing"] = _as_float(
        pointer.get("smoothing"), 0.35, 0.05, 0.95
    )
    pointer["dead_zone"] = _as_float(
        pointer.get("dead_zone"), 0.012, 0.0, 0.2
    )
    pointer["click_cooldown_ms"] = _as_int(
        pointer.get("click_cooldown_ms"), 350, 100, 2000
    )
    pointer["scroll_speed"] = _as_int(
        pointer.get("scroll_speed"), 3, 1, 20
    )
    pointer["optical_flow"] = bool(pointer.get("optical_flow", True))
    dynamic = settings["dynamic"]
    dynamic["swipe_distance"] = _as_float(
        dynamic.get("swipe_distance"), 0.17, 0.05, 0.6
    )
    dynamic["window_ms"] = _as_int(
        dynamic.get("window_ms"), 450, 100, 2000
    )
    dynamic["circle_min_angle"] = _as_int(
        dynamic.get("circle_min_angle"), 300, 90, 720
    )
    dynamic["push_pull_ratio"] = _as_float(
        dynamic.get("push_pull_ratio"), 0.25, 0.05, 0.9
    )
    two_hands = settings["two_hands"]
    two_hands["enabled"] = bool(two_hands.get("enabled", True))
    two_hands["zoom_ratio"] = _as_float(
        two_hands.get("zoom_ratio"), 0.12, 0.03, 0.8
    )
    two_hands["rotate_degrees"] = _as_int(
        two_hands.get("rotate_degrees"), 18, 5, 90
    )

    profiles = {
        name: {
            key: dict(value)
            for key, value in actions.items()
        }
        for name, actions in DEFAULT_PROFILES.items()
    }
    raw_profiles = raw.get("profiles")
    if isinstance(raw_profiles, dict):
        for name, actions in raw_profiles.items():
            name = str(name).strip()
            if name and isinstance(actions, dict):
                profiles.setdefault(name, {}).update(
                    _normalize_actions(actions)
                )
    legacy_actions = _normalize_actions(raw.get("actions"))
    if legacy_actions:
        profiles["media"].update(legacy_actions)
        profiles.setdefault("jarvis", {}).update(legacy_actions)
    profile = str(settings.get("profile") or "media").strip().lower()
    settings["profile"] = profile if profile in profiles else "media"
    settings["profiles"] = profiles
    settings["actions"] = profiles[settings["profile"]]
    return performance.clamp_gestures(settings)


def _model_path():
    candidates = [
        MODELS_DIR / "hand_landmarker.task",
        resource_path("models", "hand_landmarker.task"),
        BASE_DIR / "models" / "hand_landmarker.task",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _dist(a, b):
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _hand_size(landmarks):
    # Расстояние запястье -> основание среднего пальца, умноженное
    # на диагональ ладони, даёт устойчивый масштаб для жестов.
    base = _dist(landmarks[0], landmarks[9])
    span = _dist(landmarks[5], landmarks[17])
    return max(0.03, base + span * 0.5)


def _extended(landmarks, tip, pip, mcp, wrist=0):
    tip_w = _dist(landmarks[tip], landmarks[wrist])
    pip_w = _dist(landmarks[pip], landmarks[wrist])
    mcp_w = _dist(landmarks[mcp], landmarks[wrist])
    if tip_w <= pip_w * 1.06:
        return False
    if pip_w < mcp_w * 0.92:
        return False
    return _dist(landmarks[tip], landmarks[pip]) > _hand_size(landmarks) * 0.06


def _thumb_extended(landmarks):
    tip_w = _dist(landmarks[4], landmarks[0])
    ip_w = _dist(landmarks[3], landmarks[0])
    tip_index = _dist(landmarks[4], landmarks[5])
    ip_index = _dist(landmarks[3], landmarks[5])
    return tip_w > ip_w * 1.06 and tip_index > ip_index * 1.08


def _finger_states(landmarks):
    thumb = _thumb_extended(landmarks)
    index = _extended(landmarks, 8, 6, 5)
    middle = _extended(landmarks, 12, 10, 9)
    ring = _extended(landmarks, 16, 14, 13)
    pinky = _extended(landmarks, 20, 18, 17)
    return [thumb, index, middle, ring, pinky]


def _bbox(landmarks):
    xs = [float(point.x) for point in landmarks]
    ys = [float(point.y) for point in landmarks]
    return min(xs), min(ys), max(xs), max(ys)


def _circle_label(history, window=0.9, min_angle=300):
    """Распознаёт круговое движение запястья по истории точек."""

    if history is None or len(history) < 6:
        return ""
    now = time.monotonic()
    recent = [item for item in history if now - item[0] <= window]
    if len(recent) < 6:
        return ""
    xs = [float(item[1]) for item in recent]
    ys = [float(item[2]) for item in recent]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    angles = []
    radius = 0.0
    for x, y in zip(xs, ys, strict=False):
        dx = x - cx
        dy = y - cy
        radius += math.hypot(dx, dy)
        angles.append(math.atan2(dy, dx))
    radius /= len(recent)
    if radius < 0.045:
        return ""
    total = 0.0
    previous = angles[0]
    for angle in angles[1:]:
        delta = angle - previous
        while delta > math.pi:
            delta -= math.tau
        while delta < -math.pi:
            delta += math.tau
        total += delta
        previous = angle
    if abs(math.degrees(total)) < float(min_angle):
        return ""
    return "circle_cw" if total > 0 else "circle_ccw"


def _gesture_from_landmarks(
    landmarks,
    history,
    swipe_window=SWIPE_WINDOW,
    swipe_distance=SWIPE_DISTANCE,
    circle_min_angle=300,
):
    fingers = _finger_states(landmarks)
    count = sum(1 for value in fingers if value)
    thumb, index, middle, ring, pinky = fingers
    size = _hand_size(landmarks)
    pinch = _dist(landmarks[4], landmarks[8]) / size

    # Свайпы и круги проверяем раньше статических жестов.
    if history is not None and len(history) >= 3 and count >= 3:
        now = time.monotonic()
        recent = [item for item in history if now - item[0] <= swipe_window]
        circle = _circle_label(
            history,
            window=max(0.5, swipe_window * 2.1),
            min_angle=circle_min_angle,
        )
        if circle:
            return circle, fingers, pinch
        if len(recent) >= 3:
            dx = recent[-1][1] - recent[0][1]
            dy = recent[-1][2] - recent[0][2]
            if abs(dx) >= swipe_distance and abs(dx) > abs(dy) * 1.15:
                return ("swipe_right" if dx > 0 else "swipe_left"), fingers, pinch
            if abs(dy) >= swipe_distance and abs(dy) > abs(dx) * 1.15:
                return ("swipe_down" if dy > 0 else "swipe_up"), fingers, pinch

    if pinch < 0.08 and middle and ring and pinky and not index:
        return "ok", fingers, pinch

    if pinch < 0.055:
        return "pinch", fingers, pinch

    if thumb and index and not middle and not ring and not pinky:
        return "l_shape", fingers, pinch

    if index and pinky and not middle and not ring:
        return "rock", fingers, pinch

    if thumb and pinky and not index and not middle and not ring:
        wrist_y = float(landmarks[0].y)
        tip_y = float(landmarks[4].y)
        if tip_y < wrist_y - 0.22:
            return "call_me", fingers, pinch
        return "shaka", fingers, pinch

    if index and middle and ring and pinky:
        return "open_palm", fingers, pinch

    if count == 0:
        return "fist", fingers, pinch

    if index and middle and not ring and not pinky:
        return "peace", fingers, pinch

    if index and not middle and not ring and not pinky:
        return "point", fingers, pinch

    if thumb and not index and not middle and not ring and not pinky:
        wrist_y = float(landmarks[0].y)
        tip_y = float(landmarks[4].y)
        if tip_y < wrist_y - 0.06:
            return "thumbs_up", fingers, pinch
        if tip_y > wrist_y + 0.06:
            return "thumbs_down", fingers, pinch

    if count == 4:
        return "fingers_4", fingers, pinch
    if count == 3:
        return "fingers_3", fingers, pinch
    if count == 2:
        return "peace", fingers, pinch
    return "", fingers, pinch


def _hand_center(landmarks):
    return (
        sum(float(point.x) for point in landmarks) / len(landmarks),
        sum(float(point.y) for point in landmarks) / len(landmarks),
    )


def _two_hand_gesture(hands, previous, config):
    """Распознаёт рамку, зум, поворот и хлопок двумя руками."""

    if len(hands) < 2:
        return ""
    left, right = hands[0], hands[1]
    left_center = _hand_center(left)
    right_center = _hand_center(right)
    distance = math.hypot(
        left_center[0] - right_center[0],
        left_center[1] - right_center[1],
    )
    angle = math.degrees(
        math.atan2(
            right_center[1] - left_center[1],
            right_center[0] - left_center[0],
        )
    )
    left_fingers = _finger_states(left)
    right_fingers = _finger_states(right)
    frame_shape = (
        left_fingers[0]
        and left_fingers[1]
        and not any(left_fingers[2:])
        and right_fingers[0]
        and right_fingers[1]
        and not any(right_fingers[2:])
    )
    if frame_shape:
        return "frame"
    if distance < 0.12:
        return "clap"

    if previous:
        prev_distance, prev_angle, prev_time = previous
        if time.monotonic() - prev_time <= 0.8:
            if prev_distance > 0:
                ratio = (distance - prev_distance) / prev_distance
                zoom_ratio = float(config.get("zoom_ratio") or 0.12)
                if ratio >= zoom_ratio:
                    return "zoom_in"
                if ratio <= -zoom_ratio:
                    return "zoom_out"
            delta = angle - prev_angle
            if delta > 180:
                delta -= 360
            if delta < -180:
                delta += 360
            rotate = float(config.get("rotate_degrees") or 18)
            if abs(delta) >= rotate:
                return "rotate_cw" if delta > 0 else "rotate_ccw"
    return ""


class GestureService:
    """Ленивый MediaPipe-обработчик, подписанный на CameraService."""

    def __init__(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._queue = None
        self._landmarker = None
        self._camera = None
        self._running = False
        self._model_ready = False
        self._error = ""
        self._settings = load_gesture_settings()
        self._hand = ""
        self._hands = 0
        self._last_gesture = ""
        self._last_action = ""
        self._last_at = 0.0
        self._frames = 0
        self._fps = 0.0
        self._fps_mark = time.monotonic()
        self._candidate = ""
        self._candidate_frames = 0
        self._candidate_since = 0.0
        self._last_emit = 0.0
        self._last_emitted = ""
        self._release_mark = 0.0
        self._history = deque(maxlen=16)
        self._size_history = deque(maxlen=16)
        self._last_timestamp_ms = 0
        self._two_hand_previous = None
        self._pointer_active = False
        self._pointer_x = 0.5
        self._pointer_y = 0.5
        self._pointer_pinched = False
        self._pointer_pinch_started = 0.0
        self._pointer_pinch_origin = (0.0, 0.0)
        self._pointer_dragging = False
        self._pointer_last_click = 0.0
        self._pointer_scroll_y = None
        self._prev_gray = None
        self._prev_tip = None
        self._last_overlay_at = 0.0
        # start/stop переводят сервис между состояниями последовательно:
        # иначе новый landmarker появлялся, пока старый поток ещё
        # закрывал MediaPipe, и detect падал с
        # "cannot schedule new futures after shutdown".
        self._transition = threading.Lock()
        self._mp = None
        self._landmarker_key = None

    # ------------------------------------------------------------------
    # Управление
    # ------------------------------------------------------------------

    def start(self, settings=None):
        # Последовательный переход: stop() дожидается старого потока
        # раньше, чем новый получит landmarker.
        with self._transition:
            return self._start(settings)

    def _start(self, settings=None):
        with self._lock:
            if self._running:
                return self.status()
            self._settings = load_gesture_settings()
            if isinstance(settings, dict):
                self._settings.update(
                    {k: v for k, v in settings.items() if k in self._settings}
                )
            self._settings["enabled"] = True
            self._camera = get_camera_service()
            if not self._camera.is_running():
                self._error = "Сначала включите камеру."
                return self.status()
            self._stop.clear()
            self._error = ""
            self._fps_mark = time.monotonic()
            self._frames = 0
            self._fps = 0.0
            self._candidate = ""
            self._candidate_frames = 0
            self._candidate_since = 0.0
            self._last_emitted = ""
            self._release_mark = 0.0
            self._history.clear()
            self._size_history.clear()
            self._last_timestamp_ms = 0
            self._two_hand_previous = None
            self._reset_pointer()
            self._prev_gray = None
            self._prev_tip = None
            self._queue = queue.Queue(maxsize=2)
            self._thread = threading.Thread(
                target=self._worker,
                name="JARVIS-Gestures",
                daemon=True,
            )
            self._running = True
            self._camera.subscribe(self._on_frame)
            self._thread.start()
        log.info("[GESTURES] Запуск распознавания.")
        return self.status()

    def stop(self):
        with self._transition:
            self._stop_service()

    def _stop_service(self):
        with self._lock:
            self._stop.set()
            if self._camera is not None:
                self._camera.unsubscribe(self._on_frame)
            thread = self._thread
            self._thread = None
            self._running = False
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        # Landmarker не закрываем: следующий start() переиспользует его
        # (создание занимает ~1 с), а закрытие чужого экземпляра роняло
        # detect с "cannot schedule new futures after shutdown".
        log.info("[GESTURES] Остановлено.")

    def set_enabled(self, enabled):
        if enabled:
            return self.start()
        self.stop()
        return self.status()

    def set_profile(self, profile):
        name = str(profile or "").strip().lower()
        with self._lock:
            profiles = self._settings.get("profiles") or {}
            if name not in profiles:
                raise ValueError(f"Неизвестный профиль жестов: {profile}")
            self._settings["profile"] = name
            self._settings["actions"] = profiles[name]
            self._reset_pointer()
        profile_label = PROFILE_LABELS.get(name, name)
        if self._running:
            self._announce(f"Профиль жестов: {profile_label}.")
        try:
            from app.main import publish_ui_event

            publish_ui_event(
                "gesture_profile",
                {"profile": name, "label": profile_label},
            )
        except Exception:
            pass
        return self.status()

    def set_pointer(self, enabled):
        with self._lock:
            pointer = dict(self._settings.get("pointer") or {})
            pointer["enabled"] = bool(enabled)
            self._settings["pointer"] = pointer
            if not enabled:
                self._reset_pointer()
            if enabled and self._settings.get("profile") != "pointer":
                self._settings["profile"] = "pointer"
                self._settings["actions"] = (
                    self._settings.get("profiles") or {}
                ).get("pointer", {})
        if self._running:
            self._announce(
                "Управление курсором включено."
                if enabled
                else "Управление курсором выключено."
            )
        return self.status()

    def _active_actions(self):
        profiles = self._settings.get("profiles") or {}
        name = self._settings.get("profile") or "media"
        return profiles.get(name) or self._settings.get("actions") or {}

    def _reset_pointer(self):
        self._pointer_active = False
        self._pointer_pinched = False
        self._pointer_pinch_started = 0.0
        self._pointer_dragging = False
        self._pointer_scroll_y = None
        self._pointer_x = 0.5
        self._pointer_y = 0.5
        self._prev_tip = None

    # ------------------------------------------------------------------
    # Обработка кадров
    # ------------------------------------------------------------------

    def _on_frame(self, frame):
        queue_ref = self._queue
        if queue_ref is None or frame is None:
            return
        try:
            queue_ref.put_nowait(frame)
        except queue.Full:
            # Жестам не нужен каждый кадр: лучше пропустить, чем копить.
            pass

    def _create_landmarker(self):
        model_path = _model_path()
        if not model_path.exists():
            raise RuntimeError(
                f"Не найдена модель MediaPipe: {model_path}"
            )
        _stub_matplotlib()
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(
                model_asset_path=str(model_path)
            ),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=int(self._settings.get("num_hands") or 1),
            min_hand_detection_confidence=float(
                self._settings.get("min_detection_confidence") or 0.6
            ),
            min_hand_presence_confidence=float(
                self._settings.get("min_detection_confidence") or 0.6
            ),
            min_tracking_confidence=float(
                self._settings.get("min_tracking_confidence") or 0.5
            ),
        )
        return mp, vision, vision.HandLandmarker.create_from_options(options)

    def _landmarker_settings_key(self):
        """Настройки, при смене которых landmarker нужно пересоздать."""

        return (
            int(self._settings.get("num_hands") or 1),
            float(self._settings.get("min_detection_confidence") or 0.6),
            float(self._settings.get("min_tracking_confidence") or 0.5),
        )

    def _ensure_landmarker(self):
        """Возвращает загруженный landmarker, создавая его при необходимости.

        Экземпляр переиспользуется между запусками: создание MediaPipe
        занимает около секунды. Закрывает его только поток-владелец,
        иначе detect падает с "cannot schedule new futures after
        shutdown".
        """

        key = self._landmarker_settings_key()
        with self._lock:
            landmarker = self._landmarker
            mp = self._mp
            current_key = self._landmarker_key
        if landmarker is not None and mp is not None and current_key == key:
            return mp, landmarker
        created_mp, _, created = self._create_landmarker()
        with self._lock:
            previous = self._landmarker
            self._mp = created_mp
            self._landmarker = created
            self._landmarker_key = key
            self._model_ready = True
            self._error = ""
        if previous is not None and previous is not created:
            try:
                previous.close()
            except Exception:
                pass
        return created_mp, created

    def _discard_landmarker(self, landmarker):
        """Закрывает повреждённый landmarker: следующий start создаст новый."""

        with self._lock:
            if self._landmarker is not landmarker:
                return
            self._landmarker = None
            self._mp = None
            self._landmarker_key = None
            self._model_ready = False
        try:
            landmarker.close()
        except Exception:
            pass

    def _finish_worker(self):
        """Сбрасывает состояние, только если поток всё ещё «свой».

        stop() обнуляет ``_thread`` до join(), поэтому завершающийся
        старый поток не должен помечать остановленным только что
        запущенный новый.
        """

        current = threading.current_thread()
        with self._lock:
            if self._thread is not current:
                return
            self._thread = None
            self._running = False
            camera = self._camera
        if camera is not None:
            camera.unsubscribe(self._on_frame)

    def _worker(self):
        try:
            mp, landmarker = self._ensure_landmarker()
        except Exception as error:
            self._error = f"{type(error).__name__}: {error}"
            log.info("[GESTURES] Не удалось загрузить MediaPipe: %s", self._error)
            self._finish_worker()
            return

        log.info("[GESTURES] MediaPipe готов.")
        try:
            while not self._stop.is_set():
                try:
                    frame = self._queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                self._process(mp, landmarker, frame)
        except Exception as error:
            self._error = f"{type(error).__name__}: {error}"
            log.info("[GESTURES] Критическая ошибка: %s", self._error)
            self._discard_landmarker(landmarker)
        finally:
            self._finish_worker()

    def _process(self, mp, landmarker, frame):
        import cv2
        import numpy as np

        wants_overlay = bool(
            self._camera is not None and self._camera.has_clients()
        )
        detect_frame = frame
        detect_width = int(self._settings.get("detection_width") or 480)
        if frame.shape[1] > detect_width:
            scale = float(detect_width) / float(frame.shape[1])
            detect_frame = cv2.resize(
                frame,
                (detect_width, max(1, int(frame.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
        rgb = cv2.cvtColor(detect_frame, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp = int(time.monotonic() * 1000)
        if timestamp <= self._last_timestamp_ms:
            timestamp = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp
        result = landmarker.detect_for_video(image, timestamp)

        hand_landmarks = result.hand_landmarks or []
        handedness = result.handedness or []
        self._hands = len(hand_landmarks)
        primary = None
        if hand_landmarks:
            primary = max(
                hand_landmarks,
                key=lambda points: (
                    (_bbox(points)[2] - _bbox(points)[0])
                    * (_bbox(points)[3] - _bbox(points)[1])
                ),
            )
            side = ""
            if handedness and handedness[0]:
                side = handedness[0][0].category_name or ""
            self._hand = side

        # Без рук рисовать нечего: не копируем и не кодируем кадр,
        # чтобы MJPEG-превью показывало сырой поток телефона.
        overlay = frame.copy() if (wants_overlay and hand_landmarks) else None
        label = ""
        action_label = ""
        candidate = ""
        pinch = 1.0
        if primary is not None:
            if self._hands >= 2 and self._settings["two_hands"].get(
                "enabled", True
            ):
                now_hands = time.monotonic()
                metrics = self._two_hand_metrics(hand_landmarks)
                previous = self._two_hand_previous
                if previous and now_hands - previous[2] > 0.75:
                    previous = None
                candidate = _two_hand_gesture(
                    hand_landmarks,
                    previous,
                    self._settings["two_hands"],
                )
                if candidate or previous is None:
                    self._two_hand_previous = (
                        metrics[0],
                        metrics[1],
                        now_hands,
                    )
            else:
                self._two_hand_previous = None
                history = self._history if self._hands == 1 else None
                if history is not None:
                    history.append(
                        (
                            time.monotonic(),
                            float(primary[0].x),
                            float(primary[0].y),
                        )
                    )
                dynamic_settings = self._settings["dynamic"]
                candidate, _fingers, pinch = _gesture_from_landmarks(
                    primary,
                    history,
                    swipe_window=(
                        float(dynamic_settings.get("window_ms") or 450)
                        / 1000.0
                    ),
                    swipe_distance=float(
                        dynamic_settings.get("swipe_distance") or 0.17
                    ),
                    circle_min_angle=int(
                        dynamic_settings.get("circle_min_angle") or 300
                    ),
                )
                size = _hand_size(primary)
                self._size_history.append((time.monotonic(), size))
                dynamic = self._size_dynamic()
                if dynamic and candidate in {"open_palm", "point"}:
                    candidate = dynamic

            label = self._stabilize(candidate)
            pointer_action = self._pointer_update(
                primary, candidate, frame, pinch
            )
            if pointer_action:
                action_label = pointer_action
            if overlay is not None:
                self._draw(overlay, hand_landmarks, label)
            if label:
                emitted = self._emit(label, primary)
                action_label = emitted or action_label
        else:
            self._hand = ""
            self._two_hand_previous = None
            self._size_history.clear()
            self._decay_candidate()
            self._pointer_lost()
            if overlay is not None:
                self._draw(overlay, [], "")

        self._publish_overlay(overlay)
        self._frames += 1
        now = time.monotonic()
        elapsed = now - self._fps_mark
        if elapsed >= 1.0:
            self._fps = round(self._frames / elapsed, 1)
            self._frames = 0
            self._fps_mark = now
        with self._lock:
            self._last_gesture = label or self._last_gesture
            if action_label:
                self._last_action = action_label
                self._last_at = time.time()

    def _two_hand_metrics(self, hands):
        left_center = _hand_center(hands[0])
        right_center = _hand_center(hands[1])
        distance = math.hypot(
            left_center[0] - right_center[0],
            left_center[1] - right_center[1],
        )
        angle = math.degrees(
            math.atan2(
                right_center[1] - left_center[1],
                right_center[0] - left_center[0],
            )
        )
        return distance, angle

    def _size_dynamic(self):
        if len(self._size_history) < 5:
            return ""
        now = time.monotonic()
        recent = [
            size
            for stamp, size in self._size_history
            if now - stamp <= 0.8
        ]
        if len(recent) < 5 or recent[0] <= 0:
            return ""
        ratio = (recent[-1] - recent[0]) / recent[0]
        threshold = float(
            self._settings["dynamic"].get("push_pull_ratio") or 0.25
        )
        if ratio >= threshold:
            return "push"
        if ratio <= -threshold:
            return "pull"
        return ""

    def _refine_tip(self, frame, x, y):
        """Уточняет позицию кончика пальца оптическим потоком."""

        pointer = self._settings.get("pointer") or {}
        if not pointer.get("optical_flow", True) or frame is None:
            return x, y
        try:
            import cv2
            import numpy as np

            height, width = frame.shape[:2]
            if width <= 0 or height <= 0:
                return x, y
            small = cv2.resize(frame, (320, max(1, int(height * 320 / width))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            small_height, small_width = gray.shape[:2]
            pixel = (
                max(0.0, min(small_width - 1, x * small_width)),
                max(0.0, min(small_height - 1, y * small_height)),
            )
            if self._prev_gray is not None and self._prev_tip is not None:
                if self._prev_gray.shape == gray.shape:
                    points = np.array(
                        [[[self._prev_tip[0], self._prev_tip[1]]]],
                        dtype=np.float32,
                    )
                    moved, status, _ = cv2.calcOpticalFlowPyrLK(
                        self._prev_gray,
                        gray,
                        points,
                        None,
                        winSize=(15, 15),
                        maxLevel=2,
                    )
                    if status is not None and status[0][0]:
                        flow_x = float(moved[0][0][0]) / small_width
                        flow_y = float(moved[0][0][1]) / small_height
                        if math.hypot(flow_x - x, flow_y - y) < 0.3:
                            x = x * 0.65 + flow_x * 0.35
                            y = y * 0.65 + flow_y * 0.35
            self._prev_gray = gray
            self._prev_tip = pixel
        except Exception:
            return x, y
        return x, y

    def _pointer_update(self, landmarks, candidate, frame, pinch):
        pointer = self._settings.get("pointer") or {}
        enabled = bool(pointer.get("enabled", False))
        if not enabled or self._settings.get("profile") != "pointer":
            if self._pointer_active:
                self._pointer_lost()
            return ""
        if candidate == "open_palm":
            self._pointer_lost()
            return "release"
        if candidate == "fist":
            self._pointer_lost()
            return "pause"
        if not _finger_states(landmarks)[1]:
            return ""
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            screen_width, screen_height = pyautogui.size()
            self._pointer_active = True
            x = max(0.0, min(1.0, float(landmarks[8].x)))
            y = max(0.0, min(1.0, float(landmarks[8].y)))
            x, y = self._refine_tip(frame, x, y)
            if candidate == "peace":
                scroll_speed = int(pointer.get("scroll_speed") or 3)
                if self._pointer_scroll_y is None:
                    self._pointer_scroll_y = y
                else:
                    delta = y - self._pointer_scroll_y
                    if abs(delta) >= 0.012:
                        pyautogui.scroll(
                            int(-delta * 900 * scroll_speed)
                        )
                        self._pointer_scroll_y = y
                return "scroll"

            self._pointer_scroll_y = None
            smoothing = float(pointer.get("smoothing") or 0.35)
            dead_zone = float(pointer.get("dead_zone") or 0.012)
            if abs(x - self._pointer_x) >= dead_zone or abs(
                y - self._pointer_y
            ) >= dead_zone:
                self._pointer_x += (x - self._pointer_x) * smoothing
                self._pointer_y += (y - self._pointer_y) * smoothing
                pyautogui.moveTo(
                    int(self._pointer_x * screen_width),
                    int(self._pointer_y * screen_height),
                    duration=0,
                )

            pinched = float(pinch) < 0.075
            now = time.monotonic()
            action = "move"
            if pinched and not self._pointer_pinched:
                self._pointer_pinched = True
                self._pointer_pinch_started = now
                self._pointer_pinch_origin = (x, y)
            elif pinched and self._pointer_pinched:
                moved = math.hypot(
                    x - self._pointer_pinch_origin[0],
                    y - self._pointer_pinch_origin[1],
                )
                if (
                    not self._pointer_dragging
                    and now - self._pointer_pinch_started >= 0.3
                    and moved >= 0.02
                ):
                    pyautogui.mouseDown()
                    self._pointer_dragging = True
                if self._pointer_dragging:
                    action = "drag"
            elif not pinched and self._pointer_pinched:
                self._pointer_pinched = False
                if self._pointer_dragging:
                    pyautogui.mouseUp()
                    self._pointer_dragging = False
                    action = "drag_end"
                else:
                    cooldown = (
                        float(pointer.get("click_cooldown_ms") or 350)
                        / 1000.0
                    )
                    if now - self._pointer_last_click <= cooldown:
                        pyautogui.click(clicks=2, interval=0.05)
                        self._pointer_last_click = 0.0
                        action = "double_click"
                    else:
                        pyautogui.click()
                        self._pointer_last_click = now
                        action = "click"
            return action
        except Exception as error:
            self._error = f"Pointer: {type(error).__name__}: {error}"
            self._reset_pointer()
            return ""

    def _pointer_lost(self):
        if self._pointer_dragging:
            try:
                import pyautogui

                pyautogui.mouseUp()
            except Exception:
                pass
        self._pointer_pinched = False
        self._pointer_dragging = False
        self._pointer_scroll_y = None
        self._pointer_active = False
        self._prev_tip = None

    def _stabilize(self, candidate):
        now = time.monotonic()
        if not candidate:
            self._decay_candidate()
            return ""
        if candidate == self._candidate:
            self._candidate_frames += 1
        else:
            self._candidate = candidate
            self._candidate_frames = 1
            self._candidate_since = now

        hold = HOLD_FRAMES.get(
            candidate, int(self._settings.get("stability_frames") or 3)
        )
        if self._candidate_frames < hold:
            return ""
        dynamic_prefixes = (
            "swipe_",
            "circle_",
            "zoom_",
            "rotate_",
            "push",
            "pull",
            "clap",
        )
        if (
            not candidate.startswith(dynamic_prefixes)
            and now - self._candidate_since < 0.22
        ):
            return ""
        if candidate == self._last_emitted:
            return ""
        # Для динамических жестов не нужен долгий cooldown.
        cooldown = float(self._settings.get("cooldown_ms") or 900) / 1000.0
        if candidate.startswith(dynamic_prefixes):
            cooldown = min(cooldown, 0.55)
        if now - self._last_emit < cooldown:
            return ""
        self._last_emit = now
        self._last_emitted = candidate
        self._release_mark = now
        self._history.clear()
        return candidate

    def _decay_candidate(self):
        now = time.monotonic()
        if self._last_emitted and now - self._release_mark > 0.5:
            self._last_emitted = ""
        if self._candidate and self._candidate_frames:
            self._candidate_frames = max(0, self._candidate_frames - 1)
            if self._candidate_frames == 0:
                self._candidate = ""

    def _publish_overlay(self, frame):
        if self._camera is None or frame is None:
            return
        try:
            if not self._camera.has_clients():
                # Никто не смотрит MJPEG — кодировать JPEG незачем.
                return
            now = time.monotonic()
            interval = 1.0 / max(1.0, performance.overlay_fps())
            if now - self._last_overlay_at < interval:
                return
            self._last_overlay_at = now
            jpeg = self._camera.encode_jpeg(frame)
            if jpeg:
                self._camera.publish_overlay(jpeg)
        except Exception as error:
            self._error = f"Overlay: {error}"

    def _draw(self, frame, hands, label):
        import cv2

        height, width = frame.shape[:2]
        for points in hands:
            for start, end in HAND_CONNECTIONS:
                if start >= len(points) or end >= len(points):
                    continue
                a = points[start]
                b = points[end]
                cv2.line(
                    frame,
                    (int(a.x * width), int(a.y * height)),
                    (int(b.x * width), int(b.y * height)),
                    (60, 200, 255),
                    2,
                    cv2.LINE_AA,
                )
            for point in points:
                cv2.circle(
                    frame,
                    (int(point.x * width), int(point.y * height)),
                    3,
                    (255, 210, 80),
                    -1,
                    cv2.LINE_AA,
                )
        if label:
            text = GESTURE_LABELS_EN.get(label, label)
            cv2.rectangle(frame, (8, 8), (8 + 9 * len(text), 34), (0, 0, 0), -1)
            cv2.putText(
                frame,
                text,
                (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (90, 230, 160),
                2,
                cv2.LINE_AA,
            )

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def _emit(self, label, landmarks):
        action = self._active_actions().get(label)
        if not isinstance(action, dict):
            action = {"kind": "none"}
        action_name = str(
            action.get("mode")
            or action.get("action")
            or action.get("kind")
            or "none"
        )
        self._publish_ui_event(label, action_name, landmarks)
        try:
            self._execute(label, action)
        except Exception as error:
            self._error = f"Действие {label}: {error}"
            log.info("[GESTURES] Ошибка действия %s: %s", label, error)
        return action_name

    def _publish_ui_event(self, label, action_name, landmarks):
        try:
            from app.main import publish_ui_event

            publish_ui_event(
                "gesture",
                {
                    "name": label,
                    "label": GESTURE_LABELS.get(label, label),
                    "action": action_name,
                    "hand": self._hand,
                    "hands": self._hands,
                    "profile": self._settings.get("profile", "media"),
                },
            )
        except Exception:
            pass

    def _execute(self, label, action):
        kind = str(action.get("kind") or "action").strip().lower()
        if kind == "none":
            return
        if kind == "command":
            text = str(action.get("text") or "").strip()
            if text:
                from app.main import submit_chat_message

                submit_chat_message(text)
            return

        if kind == "pointer":
            return
        name = str(action.get("action") or "").strip().lower()
        say = str(action.get("say") or "").strip()
        changed = False
        if name == "toggle_mic":
            changed = self._toggle_mic()
        elif name == "ensure_mic_on":
            changed = self._ensure_mic_on()
        elif name == "stop_speaking":
            self._stop_speaking()
        elif name == "screenshot":
            self._screenshot()
        elif name == "camera_snapshot":
            self._camera_snapshot()
        elif name == "set_mode":
            mode = str(action.get("mode") or "tasks").strip().lower()
            self._set_mode(mode)
        elif name == "key":
            key = str(action.get("key") or "").strip()
            if key:
                self._press(key)
        elif name == "hotkey":
            keys = action.get("keys")
            if isinstance(keys, (list, tuple)) and keys:
                self._hotkey([str(key) for key in keys])
        elif name in {
            "volumeup",
            "volumedown",
            "volumemute",
            "playpause",
            "nexttrack",
            "prevtrack",
        }:
            self._press(name)
        else:
            log.info("[GESTURES] Неизвестное действие: %s", name)
            return

        if say and self._settings.get("speak_actions", True):
            if changed or name not in {"toggle_mic", "ensure_mic_on"}:
                self._announce(say)

    def _toggle_mic(self):
        from app.main import (
            microphone_enabled,
            set_microphone_enabled,
        )

        enabled = set_microphone_enabled(not microphone_enabled())
        self._announce("Микрофон включён." if enabled else "Микрофон выключен.")
        return True

    def _ensure_mic_on(self):
        from app.main import microphone_enabled, set_microphone_enabled

        if microphone_enabled():
            return False
        set_microphone_enabled(True)
        return True

    def _stop_speaking(self):
        try:
            from app.main import stop_speaking

            stop_speaking()
        except Exception:
            pass

    def _announce(self, text):
        try:
            from app.main import announce

            announce(text)
        except Exception:
            pass

    def _set_mode(self, mode):
        try:
            from app.main import set_chat_mode

            set_chat_mode(mode)
        except Exception as error:
            self._error = f"Режим {mode}: {error}"

    def _press(self, key):
        try:
            import pyautogui

            pyautogui.press(key)
        except Exception as error:
            log.info("[GESTURES] Клавиша %s не сработала: %s", key, error)
            self._error = f"Клавиша {key}: {error}"

    def _hotkey(self, keys):
        try:
            import pyautogui

            pyautogui.hotkey(*keys)
        except Exception as error:
            log.info("[GESTURES] Hotkey %s не сработал: %s", keys, error)
            self._error = f"Hotkey {keys}: {error}"

    def _screenshot(self):
        try:
            import pyautogui

            folder = DATA_DIR / "camera_snapshots"
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / f"gesture_{int(time.time())}.png"
            pyautogui.screenshot().save(output)
        except Exception as error:
            self._error = f"Скриншот: {error}"

    def _camera_snapshot(self):
        camera = self._camera
        if camera is None:
            return
        jpeg = camera.snapshot_jpeg()
        if not jpeg:
            return
        folder = DATA_DIR / "camera_snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"camera_{int(time.time())}.jpg"
        output.write_bytes(jpeg)

    # ------------------------------------------------------------------
    # Статус
    # ------------------------------------------------------------------

    def status(self):
        with self._lock:
            return {
                "enabled": bool(self._settings.get("enabled", False)),
                "running": self._running,
                "model_ready": self._model_ready,
                "hand": self._hand,
                "hands": self._hands,
                "last_gesture": self._last_gesture,
                "last_gesture_label": GESTURE_LABELS.get(
                    self._last_gesture, self._last_gesture
                ),
                "last_action": self._last_action,
                "last_at": self._last_at,
                "fps": self._fps,
                "error": self._error,
                "num_hands": self._settings.get("num_hands", 2),
                "cooldown_ms": self._settings.get("cooldown_ms", 900),
                "profile": self._settings.get("profile", "media"),
                "profile_label": PROFILE_LABELS.get(
                    self._settings.get("profile", "media"),
                    self._settings.get("profile", "media"),
                ),
                "profiles": [
                    {"name": key, "label": value}
                    for key, value in PROFILE_LABELS.items()
                ],
                "pointer": dict(self._settings.get("pointer") or {}),
                "pointer_active": self._pointer_active,
                "pointer_profile": self._settings.get("profile")
                == "pointer",
                "actions": sorted(self._active_actions().keys()),
                "action_map": {
                    key: (
                        str(
                            value.get("mode")
                            or value.get("action")
                            or value.get("kind")
                            or "none"
                        )
                        if isinstance(value, dict)
                        else "none"
                    )
                    for key, value in self._active_actions().items()
                },
                "gestures": [
                    {"name": key, "label": value}
                    for key, value in GESTURE_LABELS.items()
                ],
            }

    @property
    def settings(self):
        with self._lock:
            return dict(self._settings)


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def get_gesture_service():
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = GestureService()
        return _SERVICE
