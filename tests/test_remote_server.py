"""Тесты удалённого доступа: бан, X-Forwarded-For, политика и токен."""

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


class _HeaderHolder:
    def __init__(self, peer, forwarded=None):
        self.client_address = (peer, 5000)
        self.headers = {}
        if forwarded is not None:
            self.headers["X-Forwarded-For"] = forwarded


class RemoteAuthUnitTests(unittest.TestCase):
    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()

    def tearDown(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()

    def test_ban_after_limit(self):
        ip = "10.0.0.1"
        for _ in range(remote_server.AUTH_FAIL_LIMIT - 1):
            remote_server._auth_failed(ip)
            self.assertFalse(remote_server._auth_banned(ip))
        remote_server._auth_failed(ip)
        self.assertTrue(remote_server._auth_banned(ip))
        self.assertGreater(
            remote_server._auth_failures[ip][1], time.monotonic()
        )

    def test_counter_survives_below_limit(self):
        ip = "10.0.0.2"
        remote_server._auth_failed(ip)
        remote_server._auth_failed(ip)
        remote_server._auth_banned(ip)
        remote_server._auth_failed(ip)
        self.assertEqual(remote_server._auth_failures[ip][0], 3)

    def test_ban_expires_and_resets(self):
        ip = "10.0.0.3"
        now = time.monotonic()
        with remote_server._auth_lock:
            remote_server._auth_failures[ip] = [
                remote_server.AUTH_FAIL_LIMIT,
                now - 1.0,
                now,
            ]
        self.assertFalse(remote_server._auth_banned(ip))
        self.assertNotIn(ip, remote_server._auth_failures)

    def test_auth_ok_clears_counter(self):
        ip = "10.0.0.4"
        remote_server._auth_failed(ip)
        remote_server._auth_ok(ip)
        self.assertNotIn(ip, remote_server._auth_failures)

    def test_xff_ignored_for_direct_peer(self):
        handler = _HeaderHolder("203.0.113.9", "1.1.1.1")
        self.assertEqual(remote_server._client_ip(handler), "203.0.113.9")

    def test_xff_used_for_trusted_proxy(self):
        handler = _HeaderHolder("127.0.0.1", "198.51.100.7, 127.0.0.1")
        self.assertEqual(remote_server._client_ip(handler), "198.51.100.7")

    def test_policy_defaults_to_read_only(self):
        config = {"remote": {"token": "x"}}
        with patch.object(
            remote_server.config_module,
            "read_config_file",
            return_value=config,
        ):
            self.assertEqual(
                remote_server._remote_policy(),
                set(remote_server.READ_ONLY_METHODS),
            )

    def test_policy_allowlist(self):
        config = {
            "remote": {"allowed_methods": ["poll", "send_message"]}
        }
        with patch.object(
            remote_server.config_module,
            "read_config_file",
            return_value=config,
        ):
            self.assertEqual(
                remote_server._remote_policy(),
                {"poll", "send_message"},
            )

    def test_policy_explicit_unrestricted(self):
        config = {"remote": {"read_only": False}}
        with patch.object(
            remote_server.config_module,
            "read_config_file",
            return_value=config,
        ):
            self.assertIsNone(remote_server._remote_policy())


class RemoteHttpTests(unittest.TestCase):
    token = "test-token-123"

    def setUp(self):
        with remote_server._auth_lock:
            remote_server._auth_failures.clear()
        self.bridge = FakeBridge()
        with patch.object(
            remote_server, "get_remote_token", return_value=self.token
        ), patch.object(
            remote_server,
            "_remote_policy",
            return_value=set(remote_server.READ_ONLY_METHODS),
        ):
            self.server = remote_server.RemoteServer(self.bridge, port=0)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.host = self.server.host
        self.port = self.server.port

    def _request(self, method, path, body=None, headers=None):
        connection = HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                method, path, body=body, headers=headers or {}
            )
            response = connection.getresponse()
            return (
                response.status,
                dict(response.getheaders()),
                response.read(),
            )
        finally:
            connection.close()

    def _login(self):
        status, headers, _ = self._request(
            "POST",
            "/login",
            body=json.dumps({"token": self.token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 204)
        cookie = headers.get("Set-Cookie", "").split(";")[0]
        self.assertIn("jarvis_token=", cookie)
        return cookie

    def test_url_has_no_token(self):
        self.assertNotIn("token", self.server.url)
        self.assertEqual(
            self.server.url, f"http://{self.host}:{self.port}/"
        )

    def test_health_is_open(self):
        status, _, body = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_login_sets_httponly_cookie(self):
        status, headers, _ = self._request(
            "POST",
            "/login",
            body=json.dumps({"token": self.token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 204)
        cookie = headers.get("Set-Cookie", "")
        self.assertIn(f"jarvis_token={self.token}", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_login_wrong_token(self):
        status, headers, _ = self._request(
            "POST",
            "/login",
            body=json.dumps({"token": "wrong"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", headers)

    def test_query_token_redirects_with_cookie(self):
        status, headers, _ = self._request(
            "GET", f"/?token={self.token}"
        )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/")
        self.assertIn("HttpOnly", headers.get("Set-Cookie", ""))

    def test_static_requires_auth(self):
        status, _, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"J.A.R.V.I.S.", body)
        status, _, _ = self._request("GET", "/sw.js")
        self.assertEqual(status, 401)

    def test_cookie_grants_access(self):
        cookie = self._login()
        status, headers, body = self._request(
            "GET", "/", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"JARVIS", body)

    def test_rpc_read_only_blocks_send_message(self):
        cookie = self._login()
        status, _, _ = self._request(
            "POST",
            "/rpc",
            body=json.dumps({"method": "send_message"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": cookie,
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.bridge.calls, [])

    def test_rpc_allowed_method_reaches_bridge(self):
        cookie = self._login()
        status, _, body = self._request(
            "POST",
            "/rpc",
            body=json.dumps({"method": "poll", "id": 7}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": cookie,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.bridge.calls[0][0], "poll")
        self.assertEqual(self.bridge.calls[0][2], "remote")


if __name__ == "__main__":
    unittest.main()
