"""Тесты камеры и классификатора жестов без реального оборудования."""

import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app import gestures
from app.camera_service import (
    QUALITY_PRESETS,
    CameraService,
    _backend_candidates,
    _mask_url,
    load_camera_settings,
)


def _lm(x, y, z=0.0):
    return SimpleNamespace(x=x, y=y, z=z)


def _open_hand():
    return [
        _lm(0.50, 0.90),
        _lm(0.42, 0.82),
        _lm(0.38, 0.76),
        _lm(0.34, 0.70),
        _lm(0.30, 0.64),
        _lm(0.46, 0.68),
        _lm(0.46, 0.58),
        _lm(0.46, 0.52),
        _lm(0.46, 0.46),
        _lm(0.50, 0.67),
        _lm(0.50, 0.55),
        _lm(0.50, 0.48),
        _lm(0.50, 0.41),
        _lm(0.54, 0.68),
        _lm(0.54, 0.58),
        _lm(0.54, 0.52),
        _lm(0.54, 0.46),
        _lm(0.58, 0.70),
        _lm(0.58, 0.62),
        _lm(0.58, 0.57),
        _lm(0.58, 0.52),
    ]


def _hand_with_fingers(*extended):
    """Строит ладонь, где указанные пальцы выпрямлены, остальные согнуты.

    Порядок: thumb, index, middle, ring, pinky.
    """

    hand = _open_hand()
    # Для согнутых пальцев приближаем tip к ладони и опускаем ниже PIP.
    folds = {
        1: (0.44, 0.80),  # thumb tip
        2: (0.46, 0.72),  # index tip
        3: (0.50, 0.72),  # middle tip
        4: (0.54, 0.73),  # ring tip
        5: (0.58, 0.74),  # pinky tip
    }
    tips = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20}
    for number in range(1, 6):
        if number not in extended:
            x, y = folds[number]
            hand[tips[number]] = _lm(x, y)
    if 1 not in extended:
        hand[4] = _lm(0.44, 0.78)
    return hand


class GestureClassifierTests(unittest.TestCase):
    def test_open_palm(self):
        label, fingers, _ = gestures._gesture_from_landmarks(
            _open_hand(), None
        )
        self.assertEqual(label, "open_palm")
        self.assertTrue(all(fingers[:4]))

    def test_fist(self):
        label, fingers, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(), None
        )
        self.assertEqual(label, "fist")
        self.assertFalse(any(fingers))

    def test_point(self):
        label, _, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(2), None
        )
        self.assertEqual(label, "point")

    def test_peace(self):
        label, _, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(2, 3), None
        )
        self.assertEqual(label, "peace")

    def test_ok(self):
        hand = _hand_with_fingers(3, 4, 5)
        hand[4] = _lm(0.46, 0.70)
        hand[8] = _lm(0.47, 0.71)
        label, _, _ = gestures._gesture_from_landmarks(hand, None)
        self.assertEqual(label, "ok")

    def test_thumbs_up(self):
        label, _, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(1), None
        )
        self.assertEqual(label, "thumbs_up")

    def test_thumbs_down(self):
        hand = _hand_with_fingers(1)
        hand[4] = _lm(0.34, 0.98)
        hand[3] = _lm(0.38, 0.88)
        hand[2] = _lm(0.40, 0.80)
        label, _, _ = gestures._gesture_from_landmarks(hand, None)
        self.assertEqual(label, "thumbs_down")

    def test_swipe_right(self):
        now = time.monotonic()
        history = [
            (now - 0.30, 0.30, 0.50),
            (now - 0.15, 0.45, 0.50),
            (now, 0.65, 0.50),
        ]
        label, _, _ = gestures._gesture_from_landmarks(
            _open_hand(), history
        )
        self.assertEqual(label, "swipe_right")

    def test_swipe_left(self):
        now = time.monotonic()
        history = [
            (now - 0.30, 0.70, 0.50),
            (now - 0.15, 0.55, 0.50),
            (now, 0.35, 0.50),
        ]
        label, _, _ = gestures._gesture_from_landmarks(
            _open_hand(), history
        )
        self.assertEqual(label, "swipe_left")

    def test_default_actions_are_safe(self):
        self.assertEqual(
            gestures.DEFAULT_ACTIONS["point"]["kind"], "none"
        )
        self.assertNotIn(
            "shutdown",
            {
                str(action.get("action"))
                for action in gestures.DEFAULT_ACTIONS.values()
            },
        )

    def test_extra_static_gestures(self):
        label, _, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(1, 2), None
        )
        self.assertEqual(label, "l_shape")
        label, _, _ = gestures._gesture_from_landmarks(
            _hand_with_fingers(2, 5), None
        )
        self.assertEqual(label, "rock")
        hand = _hand_with_fingers(1, 5)
        hand[4] = _lm(0.30, 0.70)
        label, _, _ = gestures._gesture_from_landmarks(hand, None)
        self.assertEqual(label, "shaka")

    def test_circle_gesture(self):
        now = time.monotonic()
        history = [
            (now - 0.8, 0.5, 0.3),
            (now - 0.65, 0.6, 0.4),
            (now - 0.5, 0.65, 0.55),
            (now - 0.35, 0.55, 0.68),
            (now - 0.2, 0.4, 0.65),
            (now - 0.1, 0.31, 0.5),
            (now, 0.36, 0.34),
        ]
        label, _, _ = gestures._gesture_from_landmarks(
            _open_hand(), history
        )
        self.assertIn(label, {"circle_cw", "circle_ccw"})

    def test_two_hand_frame(self):
        hand = _hand_with_fingers(1, 2)
        left = [
            _lm(0.18 + (point.x - 0.5) * 0.3, point.y)
            for point in hand
        ]
        right = [
            _lm(0.78 + (point.x - 0.5) * 0.3, point.y)
            for point in hand
        ]
        label = gestures._two_hand_gesture(
            [left, right], None, {"zoom_ratio": 0.12, "rotate_degrees": 18}
        )
        self.assertEqual(label, "frame")

    def test_profile_defaults(self):
        for name in (
            "media",
            "jarvis",
            "pointer",
            "windows",
            "presentation",
        ):
            self.assertIn(name, gestures.DEFAULT_PROFILES)
        self.assertEqual(
            gestures.DEFAULT_PROFILES["pointer"]["point"]["kind"],
            "pointer",
        )


class FakeCapture:
    def __init__(self, *args, **kwargs):
        self.released = False
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def isOpened(self):
        return not self.released

    def set(self, *args):
        return True

    def get(self, prop):
        return 640.0 if prop == 3 else 480.0

    def read(self):
        if self.released:
            return False, None
        return True, self.frame.copy()

    def release(self):
        self.released = True


class CameraServiceTests(unittest.TestCase):
    def test_network_url_masks_credentials(self):
        masked = _mask_url("http://user:secret@10.0.0.5:8080/video")
        self.assertIn("***@10.0.0.5", masked)
        self.assertNotIn("secret", masked)

    def test_capture_produces_jpeg(self):
        service = CameraService()
        with patch("cv2.VideoCapture", FakeCapture):
            service.start(
                {
                    "source": "pc",
                    "index": 0,
                    "stream_fps": 20,
                    "analyze_fps": 20,
                }
            )
            try:
                deadline = time.time() + 3.0
                jpeg = b""
                while time.time() < deadline and not jpeg:
                    time.sleep(0.05)
                    jpeg = service.snapshot_jpeg()
                self.assertGreater(len(jpeg), 0)
                self.assertTrue(service.is_running())
            finally:
                service.stop()
        self.assertFalse(service.is_running())

    def test_network_source_requires_url(self):
        service = CameraService()
        service.start({"source": "network", "url": ""})
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline and not service.status()["error"]:
                time.sleep(0.05)
            self.assertIn("URL", service.status()["error"])
        finally:
            service.stop()

    def test_msmf_is_preferred_on_windows(self):
        names = [name for name, _ in _backend_candidates("auto")]
        if os.name == "nt":
            self.assertEqual(names[0], "msmf")
            self.assertIn("dshow", names)
        else:
            self.assertEqual(names, ["any"])

    def test_quality_preset_updates_stream_settings(self):
        config = {
            "camera": {
                "quality": "quality",
                "stream_fps": 5,
                "jpeg_quality": 40,
            }
        }
        with (
            patch.object(
                gestures.config_module,
                "read_config_file",
                return_value=config,
            ),
            patch(
                "app.performance.detect_tier",
                return_value="standard",
            ),
        ):
            settings = load_camera_settings()
        self.assertEqual(settings["quality"], "quality")
        self.assertEqual(
            settings["stream_fps"],
            QUALITY_PRESETS["quality"]["stream_fps"],
        )
        self.assertEqual(
            settings["jpeg_quality"],
            QUALITY_PRESETS["quality"]["jpeg_quality"],
        )


class GestureRestartTests(unittest.TestCase):
    class FakeLandmarker:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def test_landmarker_is_reused_after_stop(self):
        created = []

        def create():
            landmarker = self.FakeLandmarker()
            created.append(landmarker)
            return object(), object(), landmarker

        camera = SimpleNamespace(
            is_running=lambda: True,
            subscribe=lambda callback: None,
            unsubscribe=lambda callback: None,
            has_clients=lambda: False,
        )
        service = gestures.GestureService()

        def wait_running():
            deadline = time.time() + 3.0
            while time.time() < deadline and not service.status()["running"]:
                time.sleep(0.02)

        with patch.object(
            gestures, "get_camera_service", return_value=camera
        ), patch.object(service, "_create_landmarker", side_effect=create):
            service.start()
            wait_running()
            first = service._landmarker
            self.assertIsNotNone(first)
            service.stop()
            # Закрытие чужого landmarker роняло detect после рестарта.
            self.assertFalse(first.closed)

            service.start()
            wait_running()
            self.assertIs(service._landmarker, first)
            self.assertEqual(len(created), 1)
            service.stop()


class OverlayGatingTests(unittest.TestCase):
    def test_overlay_is_not_encoded_without_clients(self):
        encoded = []
        camera = SimpleNamespace(
            has_clients=lambda: False,
            encode_jpeg=lambda frame: encoded.append(frame) or b"jpeg",
            publish_overlay=lambda jpeg: None,
        )
        service = SimpleNamespace(
            _camera=camera,
            _last_overlay_at=0.0,
            _error="",
        )

        gestures.GestureService._publish_overlay(
            service, np.zeros((4, 4, 3), dtype=np.uint8)
        )

        self.assertEqual(encoded, [])

    def test_overlay_is_encoded_for_clients(self):
        published = []
        camera = SimpleNamespace(
            has_clients=lambda: True,
            encode_jpeg=lambda frame: b"jpeg",
            publish_overlay=published.append,
        )
        service = SimpleNamespace(
            _camera=camera,
            _last_overlay_at=0.0,
            _error="",
        )

        gestures.GestureService._publish_overlay(
            service, np.zeros((4, 4, 3), dtype=np.uint8)
        )

        self.assertEqual(published, [b"jpeg"])


if __name__ == "__main__":
    unittest.main()
