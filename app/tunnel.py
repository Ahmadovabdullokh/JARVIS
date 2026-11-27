"""Автоподъём Cloudflare-туннеля и rendezvous для мобильного клиента.

Задача: телефон должен сам находить ПК, даже если они в разных городах,
а публичный адрес меняется при каждом запуске (quick tunnel).

Схема:

1. При старте JARVIS запускается ``cloudflared`` (если ``remote.auto_tunnel``):
   named tunnel с постоянным ``remote.public_url`` или quick tunnel.
2. Актуальный URL пишется в ``data/remote_url.json``.
3. Если включён ``remote.rendezvous``, адрес шифруется AES-GCM ключом,
   выведенным из ``remote.token``, и публикуется в секретный random-топик
   ntfy (``remote.rendezvous_url``, по умолчанию ``https://ntfy.sh``).
   Телефон, зная топик и токен из QR, получает актуальный адрес и
   переподключается сам. Токен и адрес в открытом виде не публикуются.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from urllib.parse import quote

import requests

from app import config as config_module
from app.logging import get_logger
from app.paths import BASE_DIR, DATA_DIR

log = get_logger(__name__)

TUNNEL_FILE = DATA_DIR / "remote_url.json"
PID_FILE = DATA_DIR / "tunnel.pid"
DEFAULT_RENDEZVOUS_URL = "https://ntfy.sh"
DEFAULT_TUNNEL_PROTOCOL = "http2"
HEARTBEAT_SECONDS = 300.0
RETRY_SECONDS = 30.0
VERIFY_TIMEOUT = 90.0
VERIFY_INTERVAL = 5.0
HEALTH_TIMEOUT = (4.0, 6.0)
QUICK_URL_RE = re.compile(
    r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
)
PAYLOAD_PREFIX = "v1."


def _remote_section(config=None):
    if not isinstance(config, dict):
        config = config_module.read_config_file()
    remote = config.get("remote") if isinstance(config, dict) else None
    return remote if isinstance(remote, dict) else {}


def extract_quick_url(text):
    """Достаёт https://….trycloudflare.com из строки лога cloudflared."""

    found = QUICK_URL_RE.search(str(text or ""))
    if not found:
        return ""
    return found.group(0).rstrip("/") + "/"


def _clean_url(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        return ""
    return text.rstrip("/") + "/"


def ensure_rendezvous_topic():
    """Возвращает секретный топик rendezvous, создавая его при первом вызове."""

    config = config_module.read_config_file()
    remote = config.get("remote")
    if not isinstance(remote, dict):
        remote = {}
    topic = str(remote.get("rendezvous_topic") or "").strip()
    if topic:
        return topic
    topic = secrets.token_urlsafe(18)
    remote["rendezvous_topic"] = topic
    config["remote"] = remote
    try:
        config_module.save_config(config)
    except OSError as error:
        log.info("[TUNNEL] Не удалось сохранить rendezvous_topic: %s", error)
    return topic


def rendezvous_settings(create=False):
    """(enabled, base_url, topic) для публикации/чтения адреса."""

    remote = _remote_section()
    enabled = bool(remote.get("rendezvous", True))
    base = str(
        remote.get("rendezvous_url") or DEFAULT_RENDEZVOUS_URL
    ).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = DEFAULT_RENDEZVOUS_URL
    topic = str(remote.get("rendezvous_topic") or "").strip()
    if enabled and not topic and create:
        topic = ensure_rendezvous_topic()
    return enabled and bool(topic), base, topic


def rendezvous_config(create=False):
    """Данные для QR: адрес ntfy и секретный топик."""

    enabled, base, topic = rendezvous_settings(create=create)
    if not enabled:
        return {"url": "", "topic": ""}
    return {"url": base, "topic": topic}


def _token():
    from app.remote_server import get_remote_token

    return get_remote_token()


def _key(token):
    return hashlib.sha256(str(token).encode("utf-8")).digest()


def encrypt_url(url, token):
    """AES-GCM: ``v1.`` + base64url(nonce + ciphertext + tag)."""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    encrypted = AESGCM(_key(token)).encrypt(
        nonce, str(url).encode("utf-8"), None
    )
    encoded = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
    return PAYLOAD_PREFIX + encoded


def decrypt_url(payload, token):
    """Обратное преобразование (используется в тестах и диагностике)."""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    text = str(payload or "").strip()
    if not text.startswith(PAYLOAD_PREFIX):
        return ""
    try:
        raw = base64.urlsafe_b64decode(text[len(PAYLOAD_PREFIX):])
        nonce, encrypted = raw[:12], raw[12:]
        plain = AESGCM(_key(token)).decrypt(nonce, encrypted, None)
        return plain.decode("utf-8")
    except Exception:
        return ""


def read_tunnel_url():
    try:
        data = json.loads(TUNNEL_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return _clean_url(data.get("url")) if isinstance(data, dict) else ""


def _drop_quick_url():
    """Удаляет адрес quick tunnel прошлого запуска (он уже недействителен)."""

    try:
        data = json.loads(TUNNEL_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict) and data.get("provider") in {
        "cloudflare-auto",
        "cloudflare",
    }:
        try:
            TUNNEL_FILE.unlink()
        except OSError:
            pass


def current_public_url():
    remote = _remote_section()
    return _clean_url(remote.get("public_url")) or read_tunnel_url()


def write_tunnel_url(url, provider="cloudflare-auto"):
    url = _clean_url(url)
    if not url:
        return
    payload = {
        "url": url,
        "local": "http://127.0.0.1:8765",
        "provider": provider,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        TUNNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        TUNNEL_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        log.info("[TUNNEL] Не удалось сохранить адрес: %s", error)


def publish_rendezvous(url=None, token=None, timeout=10.0):
    """Публикует зашифрованный адрес в ntfy. Возвращает True при успехе."""

    enabled, base, topic = rendezvous_settings()
    if not enabled:
        return False
    target = _clean_url(url) or current_public_url()
    if not target:
        return False
    token = token or _token()
    if not token:
        return False
    try:
        payload = encrypt_url(target, token)
        response = requests.post(
            f"{base}/{quote(topic, safe='')}",
            data=payload.encode("utf-8"),
            headers={
                "Title": "JARVIS",
                "Priority": "low",
                "Cache": "yes",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        log.info("[TUNNEL] Адрес опубликован для телефона (%s).", base)
        return True
    except Exception as error:
        log.info(
            "[TUNNEL] Rendezvous недоступен: %s: %s",
            type(error).__name__,
            error,
        )
        return False


def find_cloudflared():
    candidates = [
        os.environ.get("JARVIS_CLOUDFLARED", ""),
        str(BASE_DIR / "tools" / "cloudflared.exe"),
        str(BASE_DIR / "tools" / "cloudflared"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("cloudflared") or ""


def tunnel_protocol():
    """Транспорт cloudflared: ``http2`` (TCP) или ``quic`` (UDP).

    По умолчанию HTTP/2: QUIC часто заблокирован в мобильных и
    корпоративных сетях, из-за чего туннель не регистрируется.
    Неизвестное значение → пустая строка (флаг не передаётся,
    cloudflared сам выбирает транспорт).
    """

    remote = _remote_section()
    value = str(
        remote.get("tunnel_protocol") or DEFAULT_TUNNEL_PROTOCOL
    ).strip().lower()
    return value if value in {"http2", "quic"} else ""


def build_tunnel_command(executable, name="", protocol=""):
    """Команда cloudflared с выбранным транспортом (для тестов)."""

    command = [str(executable), "tunnel"]
    if protocol in {"http2", "quic"}:
        command += ["--protocol", protocol]
    if name:
        command += ["run", name]
    else:
        command += [
            "--url",
            "http://127.0.0.1:8765",
            "--no-autoupdate",
        ]
    return command


def url_is_alive(url):
    """True, если публичный адрес реально отвечает на ``/health``."""

    url = _clean_url(url)
    if not url:
        return False
    try:
        response = requests.get(url + "health", timeout=HEALTH_TIMEOUT)
    except Exception:
        return False
    return response.status_code == 200


def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(
                0x1000, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _write_pid(pid):
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(pid), encoding="utf-8")
    except OSError:
        pass


def _clear_pid():
    try:
        PID_FILE.unlink()
    except OSError:
        pass


class TunnelManager:
    """Держит cloudflared и heartbeat rendezvous, пока работает JARVIS."""

    def __init__(self):
        self._process = None
        self._stop = threading.Event()
        self._url = ""
        self._pending_url = ""
        self._heartbeat_thread = None
        self._reader_thread = None
        self._verify_thread = None

    def start(self):
        remote = _remote_section()
        auto = bool(remote.get("auto_tunnel", False))
        public = _clean_url(remote.get("public_url"))
        rendezvous_on, _base, _topic = rendezvous_settings(create=True)

        if not auto:
            if public and rendezvous_on:
                self._url = public
                self._start_heartbeat()
                return self
            log.info(
                "[TUNNEL] Автоподъём выключен "
                "(remote.auto_tunnel=false)."
            )
            return None

        running_pid = _read_pid()
        if running_pid and _pid_alive(running_pid):
            existing = read_tunnel_url() or public
            if existing:
                self._url = existing
                self._start_heartbeat()
                log.info(
                    "[TUNNEL] Туннель уже запущен (PID %s): %s",
                    running_pid,
                    existing,
                )
            else:
                log.info(
                    "[TUNNEL] Туннель уже запущен (PID %s).",
                    running_pid,
                )
            return self

        name = str(remote.get("tunnel_name") or "").strip()
        if not name and public:
            # Постоянный адрес задан, но named tunnel не настроен:
            # не плодим quick tunnel с другим URL.
            log.info(
                "[TUNNEL] remote.public_url задан без remote.tunnel_name; "
                "туннель должен быть запущен отдельно."
            )
            self._url = public
            self._start_heartbeat()
            return self

        executable = find_cloudflared()
        if not executable:
            log.info(
                "[TUNNEL] cloudflared не найден: положите tools/"
                "cloudflared.exe или задайте JARVIS_CLOUDFLARED."
            )
            return None

        protocol = tunnel_protocol()
        if name:
            command = build_tunnel_command(executable, name, protocol)
            provider = "cloudflare-named"
            initial_url = public
        else:
            # Quick tunnel всегда выдаёт новый URL: старый адрес из
            # прошлого запуска не должен попасть в QR/rendezvous.
            _drop_quick_url()
            command = build_tunnel_command(executable, "", protocol)
            provider = "cloudflare-auto"
            initial_url = ""

        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
            )
        except OSError as error:
            log.info(
                "[TUNNEL] cloudflared не запустился: %s: %s",
                type(error).__name__,
                error,
            )
            return None

        _write_pid(self._process.pid)
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="JARVIS-TunnelLog",
            daemon=True,
        )
        self._reader_thread.start()
        log.info(
            "[TUNNEL] cloudflared запущен (PID %s, %s, protocol=%s).",
            self._process.pid,
            provider,
            protocol or "default",
        )
        if initial_url:
            self._schedule_verify(initial_url, provider)
        return self

    def _read_output(self):
        if self._process is None or self._process.stdout is None:
            return
        for line in self._process.stdout:
            text = line.strip()
            if not text:
                continue
            quick = extract_quick_url(text)
            if quick:
                self._schedule_verify(quick, "cloudflare-auto")
            elif "Registered tunnel connection" in text:
                log.info("[TUNNEL] Соединение с Cloudflare установлено.")
            elif " ERR " in text or text.startswith("ERR"):
                log.info("[TUNNEL] %s", text[:300])

    def _schedule_verify(self, url, provider):
        """Проверяет адрес и только потом отдаёт его телефону."""

        url = _clean_url(url)
        if not url or self._stop.is_set():
            return
        if url == self._url:
            self._start_heartbeat()
            return
        if url == self._pending_url and self._verify_thread is not None \
                and self._verify_thread.is_alive():
            return
        self._pending_url = url
        self._verify_thread = threading.Thread(
            target=self._verify_url,
            args=(url, provider),
            name="JARVIS-TunnelVerify",
            daemon=True,
        )
        self._verify_thread.start()

    def _verify_url(self, url, provider):
        deadline = time.monotonic() + VERIFY_TIMEOUT
        while not self._stop.is_set() and time.monotonic() < deadline:
            if url_is_alive(url):
                if not self._stop.is_set():
                    self._set_url(url, provider)
                    log.info(
                        "[TUNNEL] Адрес туннеля подтверждён: %s", url
                    )
                return
            if self._stop.wait(VERIFY_INTERVAL):
                return
        if not self._stop.is_set():
            log.info(
                "[TUNNEL] Адрес %s не подтвердился за %.0f c: "
                "телефон получит LAN-адрес.",
                url,
                VERIFY_TIMEOUT,
            )

    def _set_url(self, url, provider):
        url = _clean_url(url)
        if not url:
            return
        self._url = url
        write_tunnel_url(url, provider=provider)
        publish_rendezvous(url)
        self._start_heartbeat()

    def _start_heartbeat(self):
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        enabled, _base, _topic = rendezvous_settings()
        if not enabled:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="JARVIS-TunnelRendezvous",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            target = self._url or current_public_url()
            alive = bool(target) and url_is_alive(target)
            published = alive and publish_rendezvous(target)
            if target and not alive:
                log.info(
                    "[TUNNEL] Rendezvous: %s не отвечает, публикация "
                    "отложена.",
                    target,
                )
            if self._stop.wait(
                    HEARTBEAT_SECONDS if published else RETRY_SECONDS):
                break

    def stop(self):
        self._stop.set()
        process = self._process
        owned = process is not None
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            self._process = None
        if not owned:
            # Туннель достался от другого процесса (PID-файл жив):
            # не трогаем ни его PID, ни его адрес.
            log.info("[TUNNEL] Остановлен (внешний туннель не затронут).")
            return
        _clear_pid()
        try:
            data = json.loads(TUNNEL_FILE.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and data.get("provider") in {
                "cloudflare-auto",
            }:
                TUNNEL_FILE.unlink()
        except (OSError, ValueError):
            pass
        log.info("[TUNNEL] Остановлен.")


def start_auto_tunnel():
    """Создаёт и запускает менеджер; None, если автоподъём не нужен."""

    manager = TunnelManager()
    try:
        return manager.start()
    except Exception as error:
        log.info(
            "[TUNNEL] Не удалось запустить: %s: %s",
            type(error).__name__,
            error,
        )
        try:
            manager.stop()
        except Exception:
            pass
        return None
