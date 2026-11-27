"""Автотуннель, rendezvous и шифрование адреса."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import tunnel


class QuickUrlTests(unittest.TestCase):

    def test_extracts_public_url_from_cloudflared_log(self):
        line = (
            "2026-11-26T20:00:00Z INF |  "
            "https://quiet-river-1234.trycloudflare.com  |"
        )
        self.assertEqual(
            tunnel.extract_quick_url(line),
            "https://quiet-river-1234.trycloudflare.com/",
        )

    def test_ignores_non_tunnel_lines(self):
        self.assertEqual(tunnel.extract_quick_url("INF ok"), "")


class RendezvousCryptoTests(unittest.TestCase):

    def test_encrypt_decrypt_roundtrip(self):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography не установлена")
        payload = tunnel.encrypt_url(
            "https://abc.trycloudflare.com/", "secret-token"
        )
        self.assertTrue(payload.startswith("v1."))
        self.assertNotIn("trycloudflare", payload)
        self.assertEqual(
            tunnel.decrypt_url(payload, "secret-token"),
            "https://abc.trycloudflare.com/",
        )
        self.assertEqual(tunnel.decrypt_url(payload, "wrong-token"), "")

    def test_publish_uses_encrypted_body_and_topic(self):
        calls = []

        class Response:
            def raise_for_status(self):
                pass

        def fake_post(url, data=None, headers=None, timeout=None):
            calls.append((url, data, headers, timeout))
            return Response()

        with patch.object(
            tunnel,
            "rendezvous_settings",
            return_value=(True, "https://ntfy.sh", "topic-123"),
        ), patch.object(
            tunnel,
            "current_public_url",
            return_value="https://abc.trycloudflare.com/",
        ), patch.object(
            tunnel.requests, "post", side_effect=fake_post
        ):
            ok = tunnel.publish_rendezvous(token="secret-token")

        self.assertTrue(ok)
        self.assertEqual(calls[0][0], "https://ntfy.sh/topic-123")
        body = calls[0][1].decode("utf-8")
        self.assertTrue(body.startswith("v1."))
        self.assertNotIn("trycloudflare", body)
        self.assertEqual(
            tunnel.decrypt_url(body, "secret-token"),
            "https://abc.trycloudflare.com/",
        )

    def test_rendezvous_disabled_does_not_publish(self):
        with patch.object(
            tunnel,
            "rendezvous_settings",
            return_value=(False, "https://ntfy.sh", ""),
        ), patch.object(tunnel.requests, "post") as post:
            self.assertFalse(tunnel.publish_rendezvous())
        post.assert_not_called()

    def test_rendezvous_config_requires_topic(self):
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={"rendezvous": True, "rendezvous_topic": ""},
        ):
            self.assertEqual(
                tunnel.rendezvous_config(create=False),
                {"url": "", "topic": ""},
            )

    def test_rendezvous_config_returns_topic(self):
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={
                "rendezvous": True,
                "rendezvous_url": "https://ntfy.example/",
                "rendezvous_topic": "abc",
            },
        ):
            self.assertEqual(
                tunnel.rendezvous_config(create=False),
                {"url": "https://ntfy.example", "topic": "abc"},
            )


class TunnelProtocolTests(unittest.TestCase):

    def test_quick_tunnel_defaults_to_http2(self):
        with patch.object(tunnel, "_remote_section", return_value={}):
            self.assertEqual(tunnel.tunnel_protocol(), "http2")
        command = tunnel.build_tunnel_command(
            "cloudflared", protocol="http2"
        )
        self.assertEqual(
            command,
            [
                "cloudflared",
                "tunnel",
                "--protocol",
                "http2",
                "--url",
                "http://127.0.0.1:8765",
                "--no-autoupdate",
            ],
        )

    def test_named_tunnel_uses_protocol_before_run(self):
        command = tunnel.build_tunnel_command(
            "cloudflared", name="jarvis", protocol="http2"
        )
        self.assertEqual(
            command,
            ["cloudflared", "tunnel", "--protocol", "http2",
             "run", "jarvis"],
        )

    def test_protocol_is_configurable(self):
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={"tunnel_protocol": "QUIC"},
        ):
            self.assertEqual(tunnel.tunnel_protocol(), "quic")
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={"tunnel_protocol": "bogus"},
        ):
            self.assertEqual(tunnel.tunnel_protocol(), "")

    def test_url_is_alive_uses_health_endpoint(self):
        calls = []

        class Response:
            status_code = 200

        def fake_get(url, timeout=None):
            calls.append((url, timeout))
            return Response()

        with patch.object(tunnel.requests, "get", side_effect=fake_get):
            self.assertTrue(
                tunnel.url_is_alive("https://abc.trycloudflare.com")
            )
        self.assertEqual(
            calls[0][0], "https://abc.trycloudflare.com/health"
        )

    def test_url_is_alive_false_when_cloudflare_530(self):
        class Response:
            status_code = 530

        with patch.object(
            tunnel.requests, "get", return_value=Response()
        ):
            self.assertFalse(
                tunnel.url_is_alive("https://abc.trycloudflare.com/")
            )

    def test_url_is_alive_false_on_error(self):
        with patch.object(
            tunnel.requests,
            "get",
            side_effect=OSError("no route"),
        ):
            self.assertFalse(
                tunnel.url_is_alive("https://abc.trycloudflare.com/")
            )


class StaleQuickUrlTests(unittest.TestCase):

    def test_drops_previous_quick_tunnel_url(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remote_url.json"
            path.write_text(
                json.dumps(
                    {"url": "https://old.trycloudflare.com/",
                     "provider": "cloudflare-auto"}
                ),
                encoding="utf-8",
            )
            with patch.object(tunnel, "TUNNEL_FILE", path):
                tunnel._drop_quick_url()
            self.assertFalse(path.exists())

    def test_keeps_named_tunnel_url(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remote_url.json"
            path.write_text(
                json.dumps(
                    {"url": "https://jarvis.example.com/",
                     "provider": "cloudflare-named"}
                ),
                encoding="utf-8",
            )
            with patch.object(tunnel, "TUNNEL_FILE", path):
                tunnel._drop_quick_url()
            self.assertTrue(path.exists())


class TunnelStartTests(unittest.TestCase):

    def test_quick_tunnel_starts_with_http2(self):
        captured = {}

        class FakeProcess:
            pid = 4242
            stdout = iter(())

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            captured["command"] = command
            return FakeProcess()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remote_url.json"
            with patch.object(tunnel, "TUNNEL_FILE", path), \
                    patch.object(
                        tunnel,
                        "_remote_section",
                        return_value={"auto_tunnel": True},
                    ), \
                    patch.object(
                        tunnel,
                        "rendezvous_settings",
                        return_value=(False, "https://ntfy.sh", ""),
                    ), \
                    patch.object(tunnel, "_read_pid", return_value=0), \
                    patch.object(
                        tunnel, "find_cloudflared",
                        return_value="cloudflared",
                    ), \
                    patch.object(tunnel, "_write_pid"), \
                    patch.object(tunnel, "_clear_pid"), \
                    patch.object(
                        tunnel.subprocess, "Popen", side_effect=fake_popen
                    ):
                manager = tunnel.TunnelManager()
                try:
                    self.assertIsNotNone(manager.start())
                finally:
                    manager.stop()

        command = captured["command"]
        self.assertEqual(command[:3], [
            "cloudflared", "tunnel", "--protocol",
        ])
        self.assertEqual(command[3], "http2")
        self.assertIn("--url", command)
        self.assertFalse(path.exists())


class TunnelFileTests(unittest.TestCase):

    def test_write_and_read_tunnel_url(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remote_url.json"
            with patch.object(tunnel, "TUNNEL_FILE", path), patch.object(
                tunnel, "_remote_section", return_value={}
            ):
                tunnel.write_tunnel_url(
                    "https://abc.trycloudflare.com", "cloudflare-auto"
                )
                self.assertEqual(
                    tunnel.read_tunnel_url(),
                    "https://abc.trycloudflare.com/",
                )
                self.assertEqual(
                    tunnel.current_public_url(),
                    "https://abc.trycloudflare.com/",
                )

    def test_manager_returns_none_when_auto_tunnel_disabled(self):
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={"auto_tunnel": False},
        ), patch.object(
            tunnel,
            "rendezvous_settings",
            return_value=(False, "https://ntfy.sh", ""),
        ):
            manager = tunnel.TunnelManager()
            self.assertIsNone(manager.start())
            manager.stop()

    def test_manager_returns_none_without_cloudflared(self):
        with patch.object(
            tunnel,
            "_remote_section",
            return_value={"auto_tunnel": True},
        ), patch.object(
            tunnel,
            "rendezvous_settings",
            return_value=(False, "https://ntfy.sh", ""),
        ), patch.object(
            tunnel, "_read_pid", return_value=0
        ), patch.object(
            tunnel, "find_cloudflared", return_value=""
        ):
            manager = tunnel.TunnelManager()
            self.assertIsNone(manager.start())
            manager.stop()


if __name__ == "__main__":
    unittest.main()
