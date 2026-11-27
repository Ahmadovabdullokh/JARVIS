"""Ссылка-приглашение и QR для подключения телефона."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import pairing


class PairingLinkTests(unittest.TestCase):

    def test_link_contains_url_and_token(self):
        link = pairing.build_pairing_link(
            "https://abc.trycloudflare.com/",
            "tok en+/=",
            name="JARVIS",
        )

        parsed = urlparse(link)
        self.assertEqual(parsed.scheme, "jarvis")
        self.assertEqual(parsed.netloc, "pair")
        query = parse_qs(parsed.query)
        self.assertEqual(
            query["url"], ["https://abc.trycloudflare.com/"]
        )
        self.assertEqual(query["token"], ["tok en+/="])
        self.assertEqual(query["name"], ["JARVIS"])
        self.assertNotIn("rdvu", query)

    def test_link_contains_rendezvous_only_when_complete(self):
        link = pairing.build_pairing_link(
            "https://abc.trycloudflare.com/",
            "token",
            rendezvous_url="https://ntfy.sh/",
            rendezvous_topic="secret-topic",
        )
        query = parse_qs(urlparse(link).query)
        self.assertEqual(query["rdvu"], ["https://ntfy.sh/"])
        self.assertEqual(query["rdvt"], ["secret-topic"])

        partial = pairing.build_pairing_link(
            "https://abc.trycloudflare.com/",
            "token",
            rendezvous_url="https://ntfy.sh/",
        )
        self.assertNotIn("rdvu", parse_qs(urlparse(partial).query))

    def test_public_url_wins_over_lan(self):
        payload = pairing.pairing_payload(
            token="secret-token",
            tailscale_url="",
            public_url="https://jarvis.example.com/",
            lan_url="http://192.168.1.5:8765/",
            local_url="http://127.0.0.1:8765/",
            with_qr=False,
        )

        self.assertEqual(payload["url"], "https://jarvis.example.com/")
        self.assertEqual(
            payload["public_url"], "https://jarvis.example.com/"
        )
        self.assertEqual(payload["lan_url"], "http://192.168.1.5:8765/")
        self.assertIn(
            "url=https%3A%2F%2Fjarvis.example.com%2F",
            payload["link"],
        )
        self.assertIn("token=secret-token", payload["link"])
        self.assertIn("lan=http%3A%2F%2F192.168.1.5%3A8765%2F",
                      payload["link"])
        self.assertEqual(
            payload["fallback_url"], "http://192.168.1.5:8765/"
        )
        self.assertEqual(payload["hint"], "")
        self.assertEqual(payload["qr"], "")

    def test_tailscale_wins_without_rendezvous(self):
        from unittest.mock import patch

        with patch(
            "app.tunnel.rendezvous_config",
            return_value={
                "url": "https://ntfy.sh",
                "topic": "topic-123",
            },
        ):
            payload = pairing.pairing_payload(
                token="secret-token",
                tailscale_url="http://100.101.102.103:8765/",
                public_url="https://jarvis.example.com/",
                lan_url="http://192.168.1.5:8765/",
                local_url="http://127.0.0.1:8765/",
                with_qr=False,
            )

        self.assertEqual(
            payload["url"], "http://100.101.102.103:8765/"
        )
        self.assertEqual(
            payload["tailscale_url"], "http://100.101.102.103:8765/"
        )
        self.assertEqual(
            payload["fallback_url"], "http://192.168.1.5:8765/"
        )
        query = parse_qs(urlparse(payload["link"]).query)
        self.assertEqual(query["url"], ["http://100.101.102.103:8765/"])
        self.assertEqual(query["lan"], ["http://192.168.1.5:8765/"])
        self.assertNotIn("rdvu", query)
        self.assertNotIn("rdvt", query)
        self.assertIn("Tailscale", payload["hint"])

    def test_lan_fallback_explains_missing_tunnel(self):
        payload = pairing.pairing_payload(
            token="t",
            tailscale_url="",
            public_url="",
            lan_url="http://192.168.1.5:8765/",
            local_url="http://127.0.0.1:8765/",
            with_qr=False,
        )

        self.assertEqual(payload["url"], "http://192.168.1.5:8765/")
        self.assertIn("192.168.1.5", payload["link"])
        self.assertIn("Wi-Fi", payload["hint"])
        self.assertIn("start_tunnel", payload["hint"])

    def test_without_usable_url_there_is_no_link(self):
        payload = pairing.pairing_payload(
            token="t",
            tailscale_url="",
            public_url="",
            lan_url="",
            local_url="",
            with_qr=False,
        )

        self.assertEqual(payload["url"], "")
        self.assertEqual(payload["link"], "")
        self.assertEqual(payload["qr"], "")

    def test_invalid_scheme_is_ignored(self):
        self.assertEqual(pairing._clean_url("ftp://example.com"), "")
        self.assertEqual(
            pairing._clean_url("https://example.com"),
            "https://example.com/",
        )

    def test_tunnel_file_with_powershell_bom_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "remote_url.json"
            path.write_bytes(
                b'\xef\xbb\xbf{"url": "https://abc.trycloudflare.com/"}'
            )
            self.assertEqual(
                pairing._read_json(path)["url"],
                "https://abc.trycloudflare.com/",
            )

    def test_payload_includes_rendezvous_from_config(self):
        from unittest.mock import patch

        with patch(
            "app.tunnel.rendezvous_config",
            return_value={
                "url": "https://ntfy.sh",
                "topic": "topic-123",
            },
        ):
            payload = pairing.pairing_payload(
                token="secret-token",
                tailscale_url="",
                public_url="https://jarvis.example.com/",
                lan_url="",
                local_url="",
                with_qr=False,
            )

        self.assertEqual(payload["rendezvous_url"], "https://ntfy.sh")
        self.assertEqual(payload["rendezvous_topic"], "topic-123")
        self.assertIn("rdvu=https%3A%2F%2Fntfy.sh", payload["link"])
        self.assertIn("rdvt=topic-123", payload["link"])

    def test_qr_is_png_data_url(self):
        if importlib.util.find_spec("qrcode") is None:
            self.skipTest("qrcode не установлен")
        data = pairing.qr_data_url(
            "jarvis://pair?url=https%3A%2F%2Fexample.com&token=x"
        )
        self.assertTrue(data.startswith("data:image/png;base64,"))
        self.assertGreater(len(data), 100)


if __name__ == "__main__":
    unittest.main()
