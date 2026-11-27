"""Проверка авторизации MJPEG-эндпоинта камеры."""

import json
import time
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from app import remote_server


class FakeBridge:
    def __init__(self):
        self.calls = []

    def handle(self, method, payload, consumer="remote"):
        self.calls.append((method, payload, consumer))
        return {"method": method, "payload": payload}


class FakeCamera:
    stream_token = "stream-secret"

    def __init__(self):
        self.running = True
        self.clients = 0
        self.frames = []
        self.frame_error = ""

    def is_running(self):
        return self.running

    def latest_jpeg(self):
        return b"\xff\xd8\xff\xe0" + b"x" * 64 + b"\xff\xd9"

    def acquire_client(self):
        self.clients += 1
        return True

    def release_client(self):
        self.clients = max(0, self.clients - 1)

    def submit_external_jpeg(
        self, jpeg, rotate=0, device="", mirror=None
    ):
        self.frames.append((jpeg, str(rotate), device, mirror))
        return self.frame_error


class CameraStreamAuthTests(unittest.TestCase):
    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()
        self.camera = FakeCamera()
        self.patch = patch.object(
            remote_server,
            "get_camera_service",
            return_value=self.camera,
        )
        self.patch.start()
        self.server = remote_server.RemoteServer(
            FakeBridge(),
            host="127.0.0.1",
            port=0,
        )
        self.server.start()
        self.addCleanup(self.server.stop)
        self.addCleanup(self.patch.stop)

    def test_stream_requires_token(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            conn.request("GET", "/camera.mjpg")
            response = conn.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
        finally:
            conn.close()

    def test_stream_accepts_stream_token(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            conn.request(
                "GET",
                "/camera.mjpg?token=" + self.camera.stream_token,
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(
                "multipart/x-mixed-replace",
                response.getheader("Content-Type", ""),
            )
            chunk = response.read(64)
            self.assertIn(b"jarvisframe", chunk)
        finally:
            self.camera.running = False
            conn.close()
            time.sleep(0.05)


class CameraFrameEndpointTests(unittest.TestCase):
    TOKEN = "test-token"

    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()
        self.camera = FakeCamera()
        camera_patch = patch.object(
            remote_server,
            "get_camera_service",
            return_value=self.camera,
        )
        token_patch = patch.object(
            remote_server,
            "get_remote_token",
            return_value=self.TOKEN,
        )
        for patcher in (camera_patch, token_patch):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bridge = FakeBridge()
        self.server = remote_server.RemoteServer(
            self.bridge,
            host="127.0.0.1",
            port=0,
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def _post_frame(self, conn, body=b"jpeg-bytes", headers=None):
        conn.request(
            "POST",
            "/camera/frame?rotate=90",
            body=body,
            headers=headers or {},
        )
        response = conn.getresponse()
        return response, response.read()

    def _auth_headers(self):
        return {
            "Authorization": "Bearer " + self.TOKEN,
            "Content-Type": "image/jpeg",
            "X-Jarvis-Device": "Pixel 7",
        }

    def test_frame_requires_token(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            response, _ = self._post_frame(
                conn, headers={"Content-Type": "image/jpeg"}
            )
            self.assertEqual(response.status, 401)
        finally:
            conn.close()

    def test_frame_is_forwarded_with_rotation_and_device(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            response, payload = self._post_frame(
                conn, headers=self._auth_headers()
            )
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(payload)["ok"])
            self.assertEqual(
                self.camera.frames,
                [(b"jpeg-bytes", "90", "Pixel 7", None)],
            )
        finally:
            conn.close()

    def test_phone_mirror_flag_is_forwarded(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            conn.request(
                "POST",
                "/camera/frame?rotate=0&mirror=0",
                body=b"jpeg-bytes",
                headers=self._auth_headers(),
            )
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(
                self.camera.frames,
                [(b"jpeg-bytes", "0", "Pixel 7", False)],
            )
        finally:
            conn.close()

    def test_frame_conflict_when_source_is_not_phone(self):
        self.camera.frame_error = "not phone source"
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            response, payload = self._post_frame(
                conn, headers=self._auth_headers()
            )
            self.assertEqual(response.status, 409)
            self.assertFalse(json.loads(payload)["ok"])
        finally:
            conn.close()

    def test_frame_reports_camera_off(self):
        self.camera.frame_error = "camera is off"
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            response, _ = self._post_frame(
                conn, headers=self._auth_headers()
            )
            self.assertEqual(response.status, 503)
        finally:
            conn.close()

    def test_keep_alive_reuses_connection(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            first, _ = self._post_frame(conn, headers=self._auth_headers())
            self.assertEqual(first.status, 200)
            sock = conn.sock
            second, _ = self._post_frame(conn, headers=self._auth_headers())
            self.assertEqual(second.status, 200)
            self.assertIs(conn.sock, sock)
            self.assertEqual(len(self.camera.frames), 2)
        finally:
            conn.close()


class AutoSwitchBridge(FakeBridge):
    """Мост, который «переключает» источник при set_camera."""

    def __init__(self, camera):
        super().__init__()
        self.camera = camera

    def handle(self, method, payload, consumer="remote"):
        result = super().handle(method, payload, consumer)
        if method == "set_camera":
            self.camera.frame_error = ""
        return result


class PhoneAutoSwitchTests(unittest.TestCase):
    TOKEN = "test-token"

    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()
        remote_server._phone_switch_last = 0.0
        self.camera = FakeCamera()
        self.camera.frame_error = "not phone source"
        self.bridge = AutoSwitchBridge(self.camera)
        patches = [
            patch.object(
                remote_server,
                "get_camera_service",
                return_value=self.camera,
            ),
            patch.object(
                remote_server,
                "get_remote_token",
                return_value=self.TOKEN,
            ),
            patch.object(
                remote_server,
                "_phone_auto_switch_enabled",
                return_value=True,
            ),
            patch.object(
                remote_server, "PHONE_SWITCH_MIN_INTERVAL", 0.0
            ),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = remote_server.RemoteServer(
            self.bridge,
            host="127.0.0.1",
            port=0,
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def test_first_frame_switches_camera_to_phone(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            conn.request(
                "POST",
                "/camera/frame?rotate=0&mirror=1",
                body=b"jpeg-bytes",
                headers={
                    "Authorization": "Bearer " + self.TOKEN,
                    "Content-Type": "image/jpeg",
                    "X-Jarvis-Device": "Pixel 7",
                },
            )
            response = conn.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
        finally:
            conn.close()

        self.assertEqual(
            self.bridge.calls,
            [
                (
                    "set_camera",
                    {"enabled": True, "source": "phone", "mirror": True},
                    "phone",
                )
            ],
        )


class LocalOnlyMethodTests(unittest.TestCase):
    TOKEN = "test-token"

    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()
        self.bridge = FakeBridge()
        patches = [
            patch.object(
                remote_server,
                "get_remote_token",
                return_value=self.TOKEN,
            ),
            # Разрешаем все методы: get_pairing всё равно должен быть
            # отклонён как локальный.
            patch.object(remote_server, "_remote_policy", return_value=None),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = remote_server.RemoteServer(
            self.bridge,
            host="127.0.0.1",
            port=0,
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def test_pairing_cannot_be_requested_remotely(self):
        conn = HTTPConnection(
            "127.0.0.1", self.server.port, timeout=5
        )
        try:
            conn.request(
                "POST",
                "/rpc",
                body=json.dumps(
                    {
                        "type": "jarvis_request",
                        "id": "1",
                        "method": "get_pairing",
                        "payload": {},
                    }
                ),
                headers={
                    "Authorization": "Bearer " + self.TOKEN,
                    "Content-Type": "application/json",
                },
            )
            response = conn.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 403)
            self.assertFalse(payload["ok"])
            self.assertEqual(self.bridge.calls, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
