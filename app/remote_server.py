"""Лёгкий HTTP-сервер удалённого доступа к JARVIS.

Отдаёт статику ``ui/`` и проксирует RPC-запросы в ``UiBridge`` —
тот же протокол ``jarvis_request`` / ``jarvis_response``, что
использует pywebview на десктопе. Слушает только localhost:
наружу сервер выставляет туннель (cloudflared/ngrok).

Авторизация — токеном ``remote.token`` из ``config.json``
(генерируется при первом запуске) или переменной
``JARVIS_REMOTE_TOKEN``. Токен передаётся в query ``?token=...``
и проверяется на каждом запросе, включая статику.
"""

import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app import config as config_module
from app.logging import get_logger
from app.paths import DATA_DIR, resource_path
from app.status import get_status

log = get_logger(__name__)

CHAT_MIRROR_FILE = DATA_DIR / "remote_chat.log"
MIRROR_EVENT_TYPES = {"user", "assistant", "system", "error"}


def _mirror_to_pc(kind, text):
    """Дублирует сообщения мобильного клиента на экран ПК.

    Пишет в консоль launcher_remote и в data/remote_chat.log,
    чтобы переписку с телефона было видно на компьютере.
    """

    line = f"[{time.strftime('%H:%M:%S')}] {kind}: {text}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with CHAT_MIRROR_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass

DEFAULT_PORT = 8765
UI_DIR = resource_path("ui")
MAX_BODY = 1024 * 1024
MAX_AUDIO_BODY = 15 * 1024 * 1024

# Методы RPC, безопасные для read-only клиента (без send_message и т.п.).
READ_ONLY_METHODS = {
    "bootstrap",
    "client_ready",
    "client_error",
    "poll",
    "get_catalog",
    "get_journal",
    "get_audit",
}

# Защита от перебора токена: после AUTH_FAIL_LIMIT неудач с одного IP
# адрес получает бан на AUTH_BAN_SECONDS секунд.
AUTH_FAIL_LIMIT = 10
AUTH_BAN_SECONDS = 120.0
_auth_failures = {}
_auth_lock = threading.Lock()
_started_at = time.monotonic()


def _client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else ""


def _auth_banned(ip):
    with _auth_lock:
        fails, banned_until = _auth_failures.get(ip, (0, 0.0))
        if time.monotonic() < banned_until:
            return True
        if time.monotonic() - banned_until > AUTH_BAN_SECONDS and fails:
            _auth_failures.pop(ip, None)
        return False


def _auth_failed(ip):
    with _auth_lock:
        fails, _ = _auth_failures.get(ip, (0, 0.0))
        fails += 1
        banned_until = (
            time.monotonic() + AUTH_BAN_SECONDS
            if fails >= AUTH_FAIL_LIMIT
            else 0.0
        )
        _auth_failures[ip] = (fails, banned_until)
        if banned_until:
            log.info(f"[REMOTE] IP {ip} забанен на {AUTH_BAN_SECONDS:.0f} c "
                     f"после {fails} неудачных попыток авторизации.")


def _auth_ok(ip):
    with _auth_lock:
        _auth_failures.pop(ip, None)


def get_remote_token():
    """Возвращает токен удалённого доступа, создавая его при первом запуске."""

    env_token = os.environ.get("JARVIS_REMOTE_TOKEN", "")
    if env_token:
        return env_token.strip()

    config = config_module.read_config_file()
    remote = config.get("remote")
    if not isinstance(remote, dict):
        remote = {}
    token = str(remote.get("token") or "").strip()
    if token:
        return token

    token = secrets.token_urlsafe(24)
    remote["token"] = token
    config["remote"] = remote
    config_module.save_config(config)
    return token


def _remote_policy():
    """Политика удалённого доступа из config.json → remote.

    remote.read_only: true — только методы наблюдения (READ_ONLY_METHODS).
    remote.allowed_methods: ["poll", "send_message", ...] — явный whitelist;
    если задан, заменяет read_only.
    """

    config = config_module.read_config_file()
    remote = config.get("remote")
    if not isinstance(remote, dict):
        remote = {}
    allowed = remote.get("allowed_methods")
    if isinstance(allowed, list) and allowed:
        return {str(m).strip() for m in allowed if str(m).strip()}
    if remote.get("read_only"):
        return set(READ_ONLY_METHODS)
    return None  # без ограничений


def make_handler(bridge, token, allowed_methods=None):
    token_bytes = token.encode("utf-8")

    class RemoteHandler(BaseHTTPRequestHandler):
        server_version = "JarvisRemote/1.0"

        def log_message(self, fmt, *args):  # тише в консоли
            log.info("[REMOTE] " + fmt % args)

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_cookie_header()
            self.end_headers()
            self.wfile.write(body)

        def _send_cookie_header(self):
            # Браузер сохраняет токен в cookie, чтобы подресурсы
            # (css/js) грузились без ?token= в URL.
            if getattr(self, "_set_cookie", False):
                self.send_header(
                    "Set-Cookie",
                    f"jarvis_token={self._token_value}; Path=/; SameSite=Lax",
                )
                self._set_cookie = False

        def _send_file(self, path):
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in {
                "application/javascript",
                "application/json",
            }:
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_cookie_header()
            self.end_headers()
            self.wfile.write(body)

        def _token_matches(self, value):
            return bool(value) and secrets.compare_digest(
                value.encode("utf-8"), token_bytes
            )

        def _authorized(self):
            self._set_cookie = False
            ip = _client_ip(self)
            if _auth_banned(ip):
                return False
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            supplied = (query.get("token") or [""])[0]
            if self._token_matches(supplied):
                self._set_cookie = True
                self._token_value = supplied
                _auth_ok(ip)
                return True
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                if self._token_matches(auth[7:].strip()):
                    _auth_ok(ip)
                    return True
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("jarvis_token="):
                    value = part.split("=", 1)[1]
                    if self._token_matches(value):
                        _auth_ok(ip)
                        return True
            _auth_failed(ip)
            return False

        def _reject(self):
            self._send_json({"ok": False, "error": "unauthorized"}, 401)

        def _safe_static_path(self, url_path):
            """Резолвит URL в файл внутри ui/, без выхода за пределы каталога."""

            rel = url_path.lstrip("/") or "index.html"
            candidate = (UI_DIR / rel).resolve()
            try:
                candidate.relative_to(UI_DIR.resolve())
            except ValueError:
                return None
            if candidate.is_dir():
                candidate = candidate / "index.html"
            if not candidate.is_file():
                return None
            return candidate

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                # Открытый healthcheck для туннеля/мониторинга:
                # отдаёт только статус, без секретов и данных.
                self._send_json(
                    {
                        "ok": True,
                        "status": get_status(),
                        "uptime_seconds": round(
                            time.monotonic() - _started_at, 1
                        ),
                    }
                )
                return
            if not self._authorized():
                self._reject()
                return
            path = self._safe_static_path(path)
            if path is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            self._send_file(path)

        def _read_body(self, limit):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > limit:
                return None
            try:
                return self.rfile.read(length)
            except OSError:
                return None

        def _transcribe_audio(self, audio_bytes):
            """Распознаёт аудио с телефона через STT-пайплайн JARVIS.

            Принимает webm/ogg/wav/mp3 и любые форматы, которые
            понимает ffmpeg; конвертирует в WAV 16 кГц mono и
            отправляет в VoiceListener.
            """

            import subprocess

            import imageio_ffmpeg
            import numpy as np

            from app.main import get_listener

            listener = get_listener()
            if listener is None or not getattr(listener, "enabled", False):
                return None, "STT недоступен: нет GROQ_API_KEY или локальной модели."

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            hidden = {}
            if os.name == "nt":
                hidden = {
                    "creationflags": subprocess.CREATE_NO_WINDOW,
                }
            try:
                result = subprocess.run(
                    [
                        ffmpeg,
                        "-loglevel", "error",
                        "-i", "pipe:0",
                        "-f", "s16le",
                        "-ar", "16000",
                        "-ac", "1",
                        "pipe:1",
                    ],
                    input=audio_bytes,
                    capture_output=True,
                    timeout=30,
                    **hidden,
                )
            except Exception as error:
                return None, f"ffmpeg: {type(error).__name__}: {error}"
            if result.returncode != 0 or not result.stdout:
                return None, "Не удалось декодировать аудио."

            pcm = np.frombuffer(result.stdout, dtype=np.int16)
            audio = pcm.astype(np.float32) / 32768.0
            if audio.size < 1600:  # < 0.1 c
                return None, "Слишком короткая запись."
            text = listener._transcribe(audio)
            return (text or ""), None

        def do_POST(self):
            if not self._authorized():
                self._reject()
                return
            parsed = urlparse(self.path)
            if parsed.path == "/stt":
                body = self._read_body(MAX_AUDIO_BODY)
                if body is None:
                    self._send_json({"ok": False, "error": "bad request"}, 400)
                    return
                text, error = self._transcribe_audio(body)
                if error:
                    self._send_json({"ok": False, "error": error}, 400)
                    return
                self._send_json({"ok": True, "text": text})
                return
            if parsed.path != "/rpc":
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            data = self._read_body(MAX_BODY)
            if data is None:
                self._send_json({"ok": False, "error": "bad request"}, 400)
                return
            try:
                data = json.loads(data.decode("utf-8"))
            except Exception:
                self._send_json({"ok": False, "error": "bad json"}, 400)
                return
            if not isinstance(data, dict):
                self._send_json({"ok": False, "error": "bad request"}, 400)
                return

            method = str(data.get("method", ""))
            if allowed_methods is not None and method not in allowed_methods:
                self._send_json(
                    {"ok": False, "error": "method not allowed"}, 403
                )
                return
            payload = data.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            try:
                result = bridge.handle(method, payload, consumer="remote")
                if method == "poll" and isinstance(result, dict):
                    for event in result.get("events") or []:
                        if not isinstance(event, dict):
                            continue
                        if event.get("type") not in MIRROR_EVENT_TYPES:
                            continue
                        payload_text = event.get("payload")
                        if isinstance(payload_text, str) and payload_text.strip():
                            _mirror_to_pc(
                                str(event.get("type", "")).upper(),
                                payload_text.strip(),
                            )
                response = {
                    "type": "jarvis_response",
                    "id": data.get("id"),
                    "ok": True,
                    "data": result,
                }
            except Exception as error:
                log.info(
                    f"[REMOTE RPC] {method}: "
                    f"{type(error).__name__}: {error}"
                )
                response = {
                    "type": "jarvis_response",
                    "id": data.get("id"),
                    "ok": False,
                    "error": str(error),
                }
            self._send_json(response)

    return RemoteHandler


class RemoteServer:
    """Обёртка над ThreadingHTTPServer с управлением жизненным циклом."""

    def __init__(self, bridge, host="127.0.0.1", port=DEFAULT_PORT):
        self.bridge = bridge
        self.host = host
        self.port = port
        self.token = get_remote_token()
        self.allowed_methods = _remote_policy()
        handler = make_handler(bridge, self.token, self.allowed_methods)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = None

    @property
    def url(self):
        return f"http://{self.host}:{self.port}/?token={self.token}"

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="JARVIS-Remote",
            daemon=True,
        )
        self._thread.start()
        log.info(f"[REMOTE] Сервер удалённого доступа: {self.url}")

    def stop(self):
        try:
            self._server.shutdown()
        except Exception:
            pass
