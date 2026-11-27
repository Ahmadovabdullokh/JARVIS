"""Источник «телефон»: приём кадров, состояние и поворот."""

import io
import time
import unittest

from PIL import Image

from app.camera_service import (
    DEFAULT_SETTINGS,
    CameraService,
)


def make_jpeg(width=40, height=20, color=(30, 120, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(
        buffer, format="JPEG", quality=80
    )
    return buffer.getvalue()


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class PhoneCameraSourceTests(unittest.TestCase):
    def setUp(self):
        self.service = CameraService()
        self.addCleanup(self.service.stop)

    def start_phone(self, **settings):
        options = {"source": "phone", "enabled": True}
        options.update(settings)
        self.service.start(options)

    def test_phone_source_starts_without_opening_device(self):
        self.start_phone()
        status = self.service.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["source"], "phone")
        self.assertEqual(status["phone_state"], "idle")

    def test_accepts_frame_and_reports_live(self):
        self.start_phone()
        error = self.service.submit_external_jpeg(
            make_jpeg(), device="Pixel 7"
        )
        self.assertEqual(error, "")
        self.assertTrue(
            wait_for(lambda: self.service.status()["phone_state"] == "live")
        )
        status = self.service.status()
        self.assertEqual(status["phone_device"], "Pixel 7")
        self.assertEqual(status["phone_frames"], 1)
        self.assertEqual(status["width"], 40)
        self.assertEqual(status["height"], 20)
        self.assertTrue(
            wait_for(lambda: self.service.status()["fps"] > 0, timeout=3.0)
        )

    def test_rotation_header_rotates_frame(self):
        self.start_phone(mirror=False)
        error = self.service.submit_external_jpeg(
            make_jpeg(40, 20), rotate=90
        )
        self.assertEqual(error, "")
        frame = self.service.latest_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[:2], (40, 20))
        self.assertEqual(self.service.status()["width"], 20)
        self.assertEqual(self.service.status()["height"], 40)

    def test_rejects_frame_when_camera_off(self):
        error = self.service.submit_external_jpeg(make_jpeg())
        self.assertEqual(error, "camera is off")

    def test_rejects_frame_from_other_source(self):
        self.service._settings = dict(DEFAULT_SETTINGS)
        self.service._settings["source"] = "pc"
        self.service._running = True
        error = self.service.submit_external_jpeg(make_jpeg())
        self.assertEqual(error, "not phone source")

    def test_rejects_broken_jpeg(self):
        self.start_phone()
        error = self.service.submit_external_jpeg(b"not-a-jpeg")
        self.assertEqual(error, "bad jpeg")

    def test_frames_go_stale_after_timeout(self):
        self.start_phone(phone_timeout=1.0)
        self.service.submit_external_jpeg(make_jpeg())
        self.assertTrue(
            wait_for(lambda: self.service.status()["phone_state"] == "live")
        )
        self.assertTrue(
            wait_for(
                lambda: self.service.status()["phone_state"] == "stale",
                timeout=4.0,
            )
        )
        self.assertIn("Телефон", self.service.status()["error"])

    def test_stale_frames_are_not_served(self):
        self.start_phone(phone_timeout=1.0)
        self.service.submit_external_jpeg(make_jpeg())
        self.assertTrue(self.service.latest_jpeg())
        self.assertTrue(
            wait_for(
                lambda: self.service.status()["phone_state"] == "stale",
                timeout=4.0,
            )
        )
        self.assertEqual(self.service.latest_jpeg(), b"")
        self.assertEqual(self.service.snapshot_jpeg(), b"")

    def test_stop_resets_phone_state(self):
        self.start_phone()
        self.service.submit_external_jpeg(make_jpeg())
        self.assertTrue(
            wait_for(lambda: self.service.status()["phone_state"] == "live")
        )
        self.service.stop()
        status = self.service.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["phone_state"], "idle")
        self.assertEqual(status["phone_frames"], 0)


if __name__ == "__main__":
    unittest.main()
