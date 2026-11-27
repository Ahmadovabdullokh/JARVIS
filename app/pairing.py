"""Подключение мобильного приложения: ссылка ``jarvis://pair`` и QR-код.

Ссылка содержит адрес сервера и токен доступа, поэтому отдаётся
только локальному UI на ПК (RPC ``get_pairing``). Удалённый клиент
этот метод вызвать не может — см. ``LOCAL_ONLY_METHODS`` в
``app/remote_server.py``.

Приоритет адресов:
1. Tailscale-адрес (``100.x.x.x``) — работает в любой сети;
2. ``remote.public_url`` из config.json (named tunnel / постоянный адрес);
3. ``data/remote_url.json`` (quick tunnel, пишется start_tunnel_cf.ps1);
4. LAN-адрес из ``data/remote_status.json`` (телефон в той же Wi-Fi);
5. локальный адрес (для отладки; с телефона недоступен).
"""

import base64
import io
import json
import os
import time
from urllib.parse import urlencode, urlsplit

from app import config as config_module
from app.logging import get_logger
from app.paths import DATA_DIR

log = get_logger(__name__)

TUNNEL_FILE = DATA_DIR / "remote_url.json"
STATUS_FILE = DATA_DIR / "remote_status.json"
PAIR_SCHEME = "jarvis"
PAIR_HOST = "pair"


def _read_json(path):
    try:
        # utf-8-sig: Windows PowerShell 5.1 Set-Content -Encoding UTF8
        # добавляет BOM, json.loads с обычным utf-8 на нём падает.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _remote_section():
    try:
        config = config_module.read_config_file() or {}
    except Exception:
        config = {}
    remote = config.get("remote")
    return remote if isinstance(remote, dict) else {}


def _clean_url(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        return ""
    return text.rstrip("/") + "/"


def _lan_ip():
    try:
        from app.remote_server import _lan_ip as resolver

        return resolver()
    except Exception:
        return "127.0.0.1"


def resolve_urls():
    """Возвращает (tailscale_url, public_url, lan_url, local_url)."""

    remote = _remote_section()
    status = _read_json(STATUS_FILE)
    tunnel = _read_json(TUNNEL_FILE)

    public = (
        _clean_url(os.environ.get("JARVIS_PUBLIC_URL"))
        or _clean_url(remote.get("public_url"))
        or _clean_url(tunnel.get("url"))
    )

    tailscale = (
        _tailscale_url_now()
        or _clean_url(status.get("tailscale_url"))
    )

    local = _clean_url(status.get("url"))
    if not local:
        port = remote.get("port") or 8765
        local = _clean_url(f"http://127.0.0.1:{port}/")

    lan = _clean_url(status.get("lan_url"))
    if not lan:
        host = str(remote.get("host") or "").strip()
        if host in {"0.0.0.0", "::", ""}:
            try:
                port = urlsplit(local).port or 8765
            except ValueError:
                port = 8765
            lan = _clean_url(f"http://{_lan_ip()}:{port}/")

    return tailscale, public, lan, local


def _tailscale_url_now():
    """Текущий адрес ПК в Tailscale или "" (если Tailscale не подключён)."""

    try:
        from app.remote_server import _tailscale_ip

        ip = _tailscale_ip()
    except Exception:
        return ""
    if not ip:
        return ""
    status = _read_json(STATUS_FILE)
    try:
        port = urlsplit(_clean_url(status.get("url"))).port
    except ValueError:
        port = None
    if not port:
        try:
            port = int(_remote_section().get("port") or 8765)
        except (TypeError, ValueError):
            port = 8765
    return _clean_url(f"http://{ip}:{port}/")


def build_pairing_link(
    url,
    token,
    name="JARVIS",
    fallback="",
    rendezvous_url="",
    rendezvous_topic="",
):
    """Собирает deep link для Android-приложения.

    ``fallback`` — запасной адрес (домашняя Wi-Fi), который приложение
    попробует, если основной публичный адрес недоступен.
    ``rendezvous_url``/``rendezvous_topic`` — канал автообновления
    публичного адреса (ntfy), чтобы телефон находил ПК после смены
    quick tunnel URL.
    """

    params = {
        "url": str(url or "").strip(),
        "token": str(token or "").strip(),
        "name": str(name or "JARVIS").strip() or "JARVIS",
    }
    fallback = str(fallback or "").strip()
    if fallback:
        params["lan"] = fallback
    rendezvous_url = str(rendezvous_url or "").strip()
    rendezvous_topic = str(rendezvous_topic or "").strip()
    if rendezvous_url and rendezvous_topic:
        params["rdvu"] = rendezvous_url
        params["rdvt"] = rendezvous_topic
    return f"{PAIR_SCHEME}://{PAIR_HOST}?{urlencode(params)}"


def qr_data_url(text):
    """PNG data URL с QR-кодом; пустая строка, если qrcode недоступен."""

    if not text:
        return ""
    try:
        import qrcode

        code = qrcode.QRCode(border=4, box_size=10)
        code.add_data(text)
        code.make(fit=True)
        image = code.make_image(
            fill_color="black", back_color="white"
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return "data:image/png;base64," + encoded
    except Exception as error:
        log.info("[PAIRING] QR не сгенерирован: %s", error)
        return ""


def pairing_payload(
    token=None,
    public_url=None,
    lan_url=None,
    local_url=None,
    tailscale_url=None,
    name="JARVIS",
    with_qr=True,
    ensure_topic=False,
):
    """Данные для панели «Подключить телефон».

    Все аргументы опциональны и нужны для тестов; в приложении
    значения берутся из config.json и data/remote_*.json.
    ``ensure_topic`` создаёт rendezvous-топик при первом показе QR.
    """

    resolved_tailscale, resolved_public, resolved_lan, resolved_local = (
        resolve_urls()
    )
    tailscale = (
        _clean_url(tailscale_url)
        if tailscale_url is not None
        else resolved_tailscale
    )
    public = _clean_url(public_url) if public_url is not None else resolved_public
    lan = _clean_url(lan_url) if lan_url is not None else resolved_lan
    local = _clean_url(local_url) if local_url is not None else resolved_local

    if token is None:
        from app.remote_server import get_remote_token

        token = get_remote_token()
    token = str(token or "").strip()

    rendezvous = {"url": "", "topic": ""}
    try:
        from app.tunnel import rendezvous_config

        rendezvous = rendezvous_config(create=ensure_topic)
    except Exception:
        rendezvous = {"url": "", "topic": ""}
    rendezvous_url = str(rendezvous.get("url") or "").strip()
    rendezvous_topic = str(rendezvous.get("topic") or "").strip()

    url = tailscale or public or lan or local
    fallback = lan if lan and lan != url else ""
    # Rendezvous нужен только для публичного туннеля: Tailscale-адрес
    # стабилен, а LAN-адресу автообновление не требуется.
    relay_rendezvous = bool(url) and url == public and not tailscale
    link = (
        build_pairing_link(
            url,
            token,
            name=name,
            fallback=fallback,
            rendezvous_url=rendezvous_url if relay_rendezvous else "",
            rendezvous_topic=rendezvous_topic if relay_rendezvous else "",
        )
        if url
        else ""
    )
    qr = qr_data_url(link) if with_qr and link else ""

    hint = ""
    if tailscale and url == tailscale:
        hint = (
            "Доступ через Tailscale: работает в любой сети, если "
            "на телефоне включён Tailscale и выполнен вход в тот же аккаунт."
        )
    elif not public:
        hint = (
            "Публичный адрес туннеля пока не найден: телефон подключится "
            "только в домашней Wi-Fi сети. Подождите несколько секунд "
            "(remote.auto_tunnel) или запустите scripts\\start_tunnel_cf.ps1, "
            "затем нажмите «Показать QR» ещё раз — адрес появится "
            "после проверки /health."
        )

    return {
        "url": url,
        "fallback_url": fallback,
        "public_url": public,
        "tailscale_url": tailscale,
        "lan_url": lan,
        "local_url": local,
        "token": token,
        "link": link,
        "qr": qr,
        "name": name,
        "rendezvous_url": rendezvous_url,
        "rendezvous_topic": rendezvous_topic,
        "hint": hint,
        "updated": int(time.time()),
    }
