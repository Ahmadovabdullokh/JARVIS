"""Лёгкий HTTP-сервер удалённого доступа к JARVIS.

Отдаёт статику ``ui/`` и проксирует RPC-запросы в ``UiBridge`` —
тот же протокол ``jarvis_request`` / ``jarvis_response``, что
использует pywebview на десктопе. Слушает только localhost:
наружу сервер выставляет туннель (cloudflared/ngrok).

Авторизация — токеном ``remote.token`` из ``config.json``
(генерируется при первом запуске) или переменной
``JARVIS_REMOTE_TOKEN``. Клиент обменивает токен на HttpOnly-cookie
через ``POST /login``; в URL токен больше не передаётся. Для
совместимости ``GET /?token=...`` один раз ставит cookie и
редиректит на чистый ``/``.
"""

import gzip
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from email.utils import formatdate
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app import config as config_module
from app.camera_service import get_camera_service, load_camera_settings
from app.logging import get_logger
from app.paths import DATA_DIR, resource_path
from app.status import get_status

log = get_logger(__name__)

CHAT_MIRROR_FILE = DATA_DIR / "remote_chat.log"
STATUS_FILE = DATA_DIR / "remote_status.json"
MIRROR_EVENT_TYPES = {
    "user",
    "assistant",
    "system",
    "error",
    "gesture",
    "gesture_profile",
}


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
MAX_FRAME_BODY = 2 * 1024 * 1024

# Статика: ?v=<hash> привязывает URL к содержимому файла, поэтому
# браузер/телефон может держать его в кэше целый год без revalidate.
_STATIC_VERSION_CACHE = {}
_STATIC_VERSION_LOCK = threading.Lock()
_INDEX_ASSET_RE = re.compile(
    r'(?P<prefix>(?:href|src)=")(?P<url>(?:css|js)/[^"?#]+)(?:\?v=[^"#]*)?"'
)
_COMPRESSIBLE_TYPES = {
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "application/xml",
    "font/ttf",
    "application/x-font-ttf",
    "image/svg+xml",
}


def _compressible(ctype):
    base = (ctype or "").split(";")[0].strip().lower()
    return base.startswith("text/") or base in _COMPRESSIBLE_TYPES


def _static_version(path):
    """Версия ассета из mtime+size — файл читать не нужно."""

    try:
        stat = path.stat()
    except OSError:
        return ""
    key = str(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _STATIC_VERSION_LOCK:
        cached = _STATIC_VERSION_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    version = hashlib.sha1(
        f"{stat.st_mtime_ns}-{stat.st_size}".encode("ascii")
    ).hexdigest()[:10]
    with _STATIC_VERSION_LOCK:
        _STATIC_VERSION_CACHE[key] = (stamp, version)
    return version


def _version_index(html):
    """Подставляет ?v=<hash> в css/js ссылки index.html."""

    root = UI_DIR.resolve()

    def replace(match):
        url = match.group("url")
        try:
            target = (UI_DIR / url).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            return match.group(0)
        version = _static_version(target)
        if not version:
            return match.group(0)
        return f"{match.group('prefix')}{url}?v={version}\""

    return _INDEX_ASSET_RE.sub(replace, html)

# Методы RPC, безопасные для read-only клиента (без send_message и т.п.).
READ_ONLY_METHODS = {
    "bootstrap",
    "client_ready",
    "client_error",
    "poll",
    "get_catalog",
    "get_journal",
    "get_audit",
    "get_camera",
    "get_camera_stream_url",
    "camera_look",
}

# Методы, недоступные по сети ни при какой политике: они возвращают
# секреты (токен в ссылке-приглашении) или управляют файлами на ПК.
LOCAL_ONLY_METHODS = {
    "get_pairing",
    "save_settings",
    "open_path",
    "reload_plugins",
}

# Автопереключение камеры на телефон: не чаще одного раза в N секунд,
# чтобы поток кадров не перезапускал захват на каждый 409/503.
PHONE_SWITCH_MIN_INTERVAL = 3.0
_phone_switch_lock = threading.Lock()
_phone_switch_last = 0.0


def _phone_auto_switch_enabled():
    try:
        return bool(
            load_camera_settings().get("phone_auto_switch", True)
        )
    except Exception:
        return True


def _switch_to_phone(bridge, mirror=None):
    """Переключает источник камеры ПК на телефон после первого кадра.

    Возвращает True, если попытка была сделана и мост её принял.
    """

    global _phone_switch_last
    now = time.monotonic()
    with _phone_switch_lock:
        if now - _phone_switch_last < PHONE_SWITCH_MIN_INTERVAL:
            return False
        _phone_switch_last = now
    payload = {"enabled": True, "source": "phone"}
    if mirror is not None:
        payload["mirror"] = bool(mirror)
    try:
        bridge.handle("set_camera", payload, consumer="phone")
    except Exception as error:
        log.info(
            "[REMOTE] Автопереключение камеры не удалось: %s: %s",
            type(error).__name__,
            error,
        )
        return False
    log.info("[REMOTE] Камера ПК переключена на источник «телефон».")
    return True

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — вход</title>
<style>
  body { margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; background:#05080f; color:#cfe8ff;
         font-family:Segoe UI,Arial,sans-serif; }
  form { display:flex; flex-direction:column; gap:12px; width:min(320px,85vw);
         padding:24px; border:1px solid #1b3a5c; border-radius:12px;
         background:#0a1220; }
  h1 { margin:0 0 4px; font-size:18px; letter-spacing:2px; }
  input { padding:10px 12px; border-radius:8px; border:1px solid #1b3a5c;
          background:#05080f; color:#cfe8ff; }
  button { padding:10px 12px; border-radius:8px; border:0; cursor:pointer;
           background:#1f6feb; color:#fff; font-weight:600; }
  p { margin:0; font-size:12px; color:#6f8ca8; }
  .err { color:#ff6b6b; }
</style>
</head>
<body>
<form id="login">
  <h1>J.A.R.V.I.S.</h1>
  <p>Введите токен удалённого доступа из config.json.</p>
  <input id="token" type="password" autocomplete="current-password"
         placeholder="Токен" required>
  <button type="submit">Войти</button>
  <p id="status"></p>
</form>
<script>
document.getElementById('login').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = document.getElementById('status');
  status.textContent = '';
  try {
    const response = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token: document.getElementById('token').value}),
    });
    if (response.ok) {
      location.reload();
    } else {
      status.textContent = 'Неверный токен.';
      status.className = 'err';
    }
  } catch (error) {
    status.textContent = 'Сервер недоступен.';
    status.className = 'err';
  }
});
</script>
</body>
</html>
"""

# Защита от перебора токена: после AUTH_FAIL_LIMIT неудач с одного IP
# адрес получает бан на AUTH_BAN_SECONDS секунд.
AUTH_FAIL_LIMIT = 10
AUTH_BAN_SECONDS = 120.0
AUTH_FAILURE_TTL = 3600.0
AUTH_MAX_TRACKED = 4096

# X-Forwarded-For учитывается только когда запрос пришёл от
# доверенного прокси (loopback или адреса из JARVIS_TRUSTED_PROXIES).
DEFAULT_TRUSTED_PROXIES = {"127.0.0.1", "::1"}

_auth_failures = {}  # ip -> [fails, banned_until, last_seen]
_auth_lock = threading.Lock()
_started_at = time.monotonic()


def _trusted_proxies():
    proxies = set(DEFAULT_TRUSTED_PROXIES)
    extra = os.environ.get("JARVIS_TRUSTED_PROXIES", "")
    proxies.update(part.strip() for part in extra.split(",") if part.strip())
    return proxies


def _lan_ip():
    """Возвращает IPv4-адрес ПК в локальной сети (без реальной отправки)."""

    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_EXE_CANDIDATES = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)
TAILSCALE_CACHE_SECONDS = 30.0
_tailscale_cache = {"ip": "", "until": 0.0}


def _tailscale_ip():
    """IPv4-адрес ПК в сети Tailscale или "" если Tailscale не подключён."""

    now = time.monotonic()
    if now < _tailscale_cache["until"]:
        return _tailscale_cache["ip"]

    executable = shutil.which("tailscale") or ""
    if not executable:
        for candidate in TAILSCALE_EXE_CANDIDATES:
            if os.path.isfile(candidate):
                executable = candidate
                break

    value = ""
    if executable:
        try:
            result = subprocess.run(
                [executable, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    text = line.strip()
                    try:
                        if ipaddress.ip_address(text) in TAILSCALE_NET:
                            value = text
                            break
                    except ValueError:
                        continue
        except (OSError, subprocess.SubprocessError):
            value = ""

    _tailscale_cache["ip"] = value
    _tailscale_cache["until"] = now + TAILSCALE_CACHE_SECONDS
    return value


def _client_ip(handler):
    peer = handler.client_address[0] if handler.client_address else ""
    forwarded = handler.headers.get("X-Forwarded-For") or ""
    if forwarded and peer in _trusted_proxies():
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            return chain[0]
    return peer


def _prune_auth_failures(now):
    stale = [
        ip
        for ip, state in _auth_failures.items()
        if now - state[2] > AUTH_FAILURE_TTL
    ]
    for ip in stale:
        _auth_failures.pop(ip, None)


def _auth_banned(ip):
    now = time.monotonic()
    with _auth_lock:
        state = _auth_failures.get(ip)
        if state is None:
            return False
        _, banned_until, last_seen = state
        if now < banned_until:
            state[2] = now
            return True
        if banned_until:
            # Срок бана истёк — счётчик начинается заново.
            _auth_failures.pop(ip, None)
            return False
        if now - last_seen > AUTH_FAILURE_TTL:
            _auth_failures.pop(ip, None)
        return False


def _auth_failed(ip):
    now = time.monotonic()
    with _auth_lock:
        state = _auth_failures.get(ip)
        fails = (state[0] if state else 0) + 1
        banned_until = (
            now + AUTH_BAN_SECONDS
            if fails >= AUTH_FAIL_LIMIT
            else 0.0
        )
        _auth_failures[ip] = [fails, banned_until, now]
        if len(_auth_failures) > AUTH_MAX_TRACKED:
            _prune_auth_failures(now)
        if banned_until:
            log.warning(
                "[REMOTE] IP %s забанен на %.0f c после %d "
                "неудачных попыток авторизации.",
                ip,
                AUTH_BAN_SECONDS,
                fails,
            )


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
    если задан, заменяет read_only. По умолчанию доступ read-only:
    полный набор методов включается только явным ``read_only: false``.
    """

    config = config_module.read_config_file()
    remote = config.get("remote")
    if not isinstance(remote, dict):
        remote = {}
    allowed = remote.get("allowed_methods")
    if isinstance(allowed, list) and allowed:
        return {str(m).strip() for m in allowed if str(m).strip()}
    if remote.get("read_only", True):
        return set(READ_ONLY_METHODS)
    return None  # явное remote.read_only: false — без ограничений


def make_handler(bridge, token, allowed_methods=None):
    token_bytes = token.encode("utf-8")

    class RemoteHandler(BaseHTTPRequestHandler):
        server_version = "JarvisRemote/1.0"
        # HTTP/1.1 + keep-alive: телефон шлёт кадры по одному соединению.
        protocol_version = "HTTP/1.1"
        timeout = 60

        def log_message(self, fmt, *args):  # тише в консоли
            log.info("[REMOTE] " + fmt % args)

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, body, status=200):
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(payload)

        def _is_secure(self):
            proto = self.headers.get("X-Forwarded-Proto") or ""
            return proto.split(",")[0].strip().lower() == "https"

        def _cookie_header(self, value):
            flags = "Path=/; HttpOnly; SameSite=Strict"
            if self._is_secure():
                flags += "; Secure"
            return f"jarvis_token={value}; {flags}"

        def _send_login_redirect(self, token_value):
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", self._cookie_header(token_value))
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()

        def _send_file(self, path, query=None):
            try:
                stat = path.stat()
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
            is_index = path.name == "index.html"
            if is_index:
                # Версии ассетов считаются на лету: править index.html
                # вручную при каждом изменении css/js больше не нужно.
                try:
                    body = _version_index(
                        body.decode("utf-8")
                    ).encode("utf-8")
                except UnicodeDecodeError:
                    pass
                etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            else:
                etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            versioned = bool((query or {}).get("v"))
            if versioned:
                cache_control = "public, max-age=31536000, immutable"
            elif is_index:
                cache_control = "no-store"
            else:
                # Файл мог измениться после пересборки — только с проверкой.
                cache_control = "no-cache"
            if etag in (self.headers.get("If-None-Match") or ""):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", formatdate(
                    stat.st_mtime, usegmt=True
                ))
                self.send_header("Cache-Control", cache_control)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            encoding = ""
            if (
                _compressible(ctype)
                and len(body) >= 1024
                and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
            ):
                compressed = gzip.compress(body, compresslevel=6)
                if len(compressed) < len(body) - 64:
                    body = compressed
                    encoding = "gzip"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", formatdate(
                stat.st_mtime, usegmt=True
            ))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Vary", "Accept-Encoding")
            if encoding:
                self.send_header("Content-Encoding", encoding)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _token_matches(self, value):
            return bool(value) and secrets.compare_digest(
                value.encode("utf-8"), token_bytes
            )

        def _authorized(self):
            ip = _client_ip(self)
            if _auth_banned(ip):
                return False
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                if self._token_matches(auth[7:].strip()):
                    _auth_ok(ip)
                    return True
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            morsel = cookie.get("jarvis_token")
            if morsel is not None and self._token_matches(morsel.value):
                _auth_ok(ip)
                return True
            _auth_failed(ip)
            return False

        def _login_token(self, body):
            text = body.decode("utf-8", "replace")
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = json.loads(text)
                except ValueError:
                    return ""
                if isinstance(data, dict):
                    return str(data.get("token") or "").strip()
                return ""
            form = parse_qs(text)
            return (form.get("token") or [""])[0].strip()

        def _handle_login(self):
            ip = _client_ip(self)
            if _auth_banned(ip):
                self._reject()
                return
            body = self._read_body(MAX_BODY)
            if body is None:
                self._send_json({"ok": False, "error": "bad request"}, 400)
                return
            supplied = self._login_token(body)
            if self._token_matches(supplied):
                _auth_ok(ip)
                self.send_response(204)
                self.send_header("Set-Cookie", self._cookie_header(supplied))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            _auth_failed(ip)
            self._send_json({"ok": False, "error": "unauthorized"}, 401)

        def _login_via_query(self, query):
            ip = _client_ip(self)
            if _auth_banned(ip):
                self._reject()
                return
            supplied = (query.get("token") or [""])[0]
            if self._token_matches(supplied):
                _auth_ok(ip)
                self._send_login_redirect(supplied)
                return
            _auth_failed(ip)
            self._reject()

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

        def _camera_authorized(self, query):
            camera = get_camera_service()
            stream_token = str(getattr(camera, "stream_token", "") or "")
            for value in query.get("token") or []:
                if stream_token and secrets.compare_digest(
                    str(value), stream_token
                ):
                    return True
                if self._token_matches(str(value)):
                    return True
            return self._authorized()

        def _stream_camera(self):
            camera = get_camera_service()
            if not camera.is_running():
                self._send_json(
                    {"ok": False, "error": "camera is off"},
                    503,
                )
                return
            if not camera.acquire_client():
                self._send_json(
                    {"ok": False, "error": "too many camera clients"},
                    503,
                )
                return
            boundary = b"--jarvisframe"
            try:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "multipart/x-mixed-replace; boundary=jarvisframe",
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.close_connection = True
                last_sent = None
                while camera.is_running():
                    jpeg = camera.latest_jpeg()
                    if not jpeg or jpeg is last_sent:
                        time.sleep(0.02)
                        continue
                    last_sent = jpeg
                    header = (
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: "
                        + str(len(jpeg)).encode("ascii")
                        + b"\r\n\r\n"
                    )
                    self.wfile.write(boundary + b"\r\n")
                    self.wfile.write(header)
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            except Exception as error:
                log.info(
                    "[CAMERA STREAM] %s: %s",
                    type(error).__name__,
                    error,
                )
            finally:
                camera.release_client()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
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
            query = parse_qs(parsed.query)
            if path == "/camera.mjpg":
                if not self._camera_authorized(query):
                    self._reject()
                    return
                self._stream_camera()
                return
            if "token" in query and path in {"/", "/index.html"}:
                self._login_via_query(query)
                return
            if not self._authorized():
                if path in {"/", "/index.html"}:
                    self._send_html(LOGIN_PAGE)
                else:
                    self._reject()
                return
            path = self._safe_static_path(path)
            if path is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            self._send_file(path, query)

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
            parsed = urlparse(self.path)
            if parsed.path == "/login":
                self._handle_login()
                return
            if not self._authorized():
                self._reject()
                return
            if parsed.path == "/camera/frame":
                body = self._read_body(MAX_FRAME_BODY)
                if body is None:
                    self._send_json({"ok": False, "error": "bad request"}, 400)
                    return
                query = parse_qs(parsed.query)
                rotate = (query.get("rotate") or ["0"])[0]
                device = self.headers.get("X-Jarvis-Device") or ""
                mirror = None
                mirror_value = (query.get("mirror") or [""])[0]
                if mirror_value in {"0", "1"}:
                    mirror = mirror_value == "1"
                camera = get_camera_service()
                error = camera.submit_external_jpeg(
                    body,
                    rotate=rotate,
                    device=device,
                    mirror=mirror,
                )
                # Первый кадр с телефона сам включает источник «phone»:
                # не нужно вручную переключать камеру в HUD.
                if (
                    error in {"not phone source", "camera is off"}
                    and _phone_auto_switch_enabled()
                    and _switch_to_phone(bridge, mirror)
                ):
                    error = camera.submit_external_jpeg(
                        body,
                        rotate=rotate,
                        device=device,
                        mirror=mirror,
                    )
                if error == "bad jpeg":
                    self._send_json({"ok": False, "error": error}, 400)
                    return
                if error == "not phone source":
                    self._send_json(
                        {
                            "ok": False,
                            "error": error,
                            "hint": "switch camera source to phone",
                        },
                        409,
                    )
                    return
                if error:
                    self._send_json({"ok": False, "error": error}, 503)
                    return
                self._send_json({"ok": True})
                return
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
            if method in LOCAL_ONLY_METHODS:
                self._send_json(
                    {
                        "ok": False,
                        "error": "method is local only",
                    },
                    403,
                )
                return
            policy = (
                allowed_methods()
                if callable(allowed_methods)
                else allowed_methods
            )
            if policy is not None and method not in policy:
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
        self.allowed_methods = _remote_policy
        handler = make_handler(bridge, self.token, self.allowed_methods)
        self._server = ThreadingHTTPServer((host, port), handler)
        # Порт 0 означает «любой свободный»: фиксируем фактический.
        self.port = self._server.server_address[1]
        self._thread = None

    @property
    def url(self):
        host = self.host
        if host in {"0.0.0.0", "::", ""}:
            host = "127.0.0.1"
        return f"http://{host}:{self.port}/"

    @property
    def lan_url(self):
        if self.host in {"127.0.0.1", "localhost"}:
            return ""
        return f"http://{_lan_ip()}:{self.port}/"

    @property
    def tailscale_url(self):
        if self.host in {"127.0.0.1", "localhost"}:
            return ""
        ip = _tailscale_ip()
        return f"http://{ip}:{self.port}/" if ip else ""

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="JARVIS-Remote",
            daemon=True,
        )
        self._thread.start()
        log.info("[REMOTE] Сервер удалённого доступа: %s", self.url)
        lan = self.lan_url
        if lan:
            log.info("[REMOTE] Для телефона в той же Wi-Fi: %s", lan)
        tailscale = self.tailscale_url
        if tailscale:
            log.info(
                "[REMOTE] Для телефона в любой сети (Tailscale): %s",
                tailscale,
            )

    def stop(self):
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass


def write_status(server):
    """Сохраняет адреса сервера для scripts\\remote_info.ps1."""
    try:
        STATUS_FILE.write_text(
            json.dumps(
                {
                    "url": server.url,
                    "lan_url": server.lan_url,
                    "tailscale_url": server.tailscale_url,
                    "updated": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
