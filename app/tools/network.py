import json
import socket
import ssl
import time

import psutil
import requests

from app.tools.common import (
    optional_import,
    powershell,
    resolve_path,
    run_command,
)


def _resolve(host, port):
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def register(registry):

    @registry.tool(
        "network_info",
        "Сетевые интерфейсы, IP, маски и шлюзы.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_info():
        lines = []
        for name, addresses in psutil.net_if_addrs().items():
            lines.append(f"[{name}]")
            for address in addresses:
                if address.family == socket.AF_INET:
                    lines.append(
                        f"  IPv4: {address.address} mask {address.netmask}"
                    )
                elif address.family == socket.AF_INET6:
                    lines.append(f"  IPv6: {address.address}")
                elif getattr(psutil, "AF_LINK", None) == address.family:
                    lines.append(f"  MAC: {address.address}")
        stats = psutil.net_io_counters(pernic=True)
        for name, counters in stats.items():
            lines.append(
                f"{name}: отправлено {counters.bytes_sent}, "
                f"получено {counters.bytes_recv}"
            )
        return "\n".join(lines)

    @registry.tool(
        "network_hostname",
        "Имя компьютера и локальные адреса.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_hostname():
        hostname = socket.gethostname()
        try:
            addresses = socket.gethostbyname_ex(hostname)
        except OSError:
            addresses = (hostname, [], [])
        return (
            f"Имя: {hostname}\n"
            f"Адреса: {', '.join(addresses[2]) or 'нет'}"
        )

    @registry.tool(
        "network_ping",
        "Пинговать узел.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["host"],
        },
        category="network",
    )
    def network_ping(host, count=4):
        result = run_command(
            ["ping", "-n", str(max(1, int(count or 4))), str(host)],
            timeout=60,
        )
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "network_dns",
        "Разрешить доменное имя в IP.",
        {
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
        category="network",
    )
    def network_dns(host):
        try:
            addresses = sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(host, None)
                }
            )
        except OSError as error:
            return f"Не удалось разрешить {host}: {error}"
        return "\n".join(addresses)

    @registry.tool(
        "network_port_check",
        "Проверить доступность TCP-порта.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "timeout": {"type": "number"},
            },
            "required": ["host", "port"],
        },
        category="network",
    )
    def network_port_check(host, port, timeout=3):
        started = time.time()
        try:
            with socket.create_connection(
                (host, int(port)), timeout=float(timeout or 3)
            ):
                elapsed = (time.time() - started) * 1000
                return f"{host}:{port} открыт ({elapsed:.0f} мс)"
        except OSError as error:
            return f"{host}:{port} недоступен: {error}"

    @registry.tool(
        "network_port_scan",
        "Просканировать диапазон портов.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "start": {"type": "integer"},
                "end": {"type": "integer"},
                "timeout": {"type": "number"},
            },
            "required": ["host", "start", "end"],
        },
        category="network",
    )
    def network_port_scan(host, start=1, end=1024, timeout=0.3):
        start = max(1, int(start or 1))
        end = min(65535, int(end or 1024))
        if end - start > 2000:
            return "Диапазон слишком большой (максимум 2000 портов)."
        open_ports = []
        for port in range(start, end + 1):
            try:
                with socket.create_connection(
                    (host, port), timeout=float(timeout or 0.3)
                ):
                    open_ports.append(port)
            except OSError:
                continue
        return (
            "Открытые порты: " + ", ".join(map(str, open_ports))
            if open_ports
            else "Открытых портов не найдено."
        )

    @registry.tool(
        "network_public_ip",
        "Показать внешний IP и геоданные.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_public_ip():
        try:
            response = requests.get(
                "https://ipinfo.io/json", timeout=10
            )
            return json.dumps(response.json(), ensure_ascii=False, indent=2)
        except Exception as error:
            return f"Не удалось получить внешний IP: {error}"

    @registry.tool(
        "network_http",
        "Выполнить HTTP-запрос.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                },
                "headers": {"type": "object"},
                "params": {"type": "object"},
                "json_body": {"type": "object"},
                "data": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["url"],
        },
        category="network",
    )
    def network_http(
        url,
        method="GET",
        headers=None,
        params=None,
        json_body=None,
        data=None,
        timeout=30,
    ):
        try:
            response = requests.request(
                str(method or "GET").upper(),
                str(url),
                headers=headers,
                params=params,
                json=json_body,
                data=data,
                timeout=float(timeout or 30),
            )
        except Exception as error:
            return f"HTTP-ошибка: {error}"
        content_type = response.headers.get("content-type", "")
        body = response.text
        if len(body) > 8000:
            body = body[:8000] + "... (обрезано)"
        return (
            f"Статус: {response.status_code}\n"
            f"Тип: {content_type}\n"
            f"Длина: {len(response.content)} байт\n\n{body}"
        )

    @registry.tool(
        "network_download",
        "Скачать файл по URL.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "path": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["url", "path"],
        },
        category="network",
    )
    def network_download(url, path, timeout=120):
        target = resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with requests.get(
                str(url),
                stream=True,
                timeout=float(timeout or 120),
            ) as response:
                response.raise_for_status()
                with open(target, "wb") as handle:
                    for chunk in response.iter_content(1024 * 64):
                        if chunk:
                            handle.write(chunk)
        except Exception as error:
            return f"Не удалось скачать: {error}"
        return f"Скачано: {target} ({target.stat().st_size} байт)"

    @registry.tool(
        "network_url_status",
        "Проверить HTTP-статус и заголовки URL.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        category="network",
    )
    def network_url_status(url):
        try:
            response = requests.head(
                str(url), allow_redirects=True, timeout=15
            )
            lines = [f"{response.status_code} {response.reason}"]
            for key, value in response.headers.items():
                lines.append(f"{key}: {value}")
            return "\n".join(lines)
        except Exception as error:
            return f"Не удалось проверить URL: {error}"

    @registry.tool(
        "network_ssl_cert",
        "Информация о SSL-сертификате сайта.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
            },
            "required": ["host"],
        },
        category="network",
    )
    def network_ssl_cert(host, port=443):
        context = ssl.create_default_context()
        try:
            with socket.create_connection(
                (host, int(port or 443)), timeout=10
            ) as sock:
                with context.wrap_socket(sock, server_hostname=host) as tls:
                    certificate = tls.getpeercert()
            return json.dumps(certificate, ensure_ascii=False, indent=2)
        except Exception as error:
            return f"Не удалось получить сертификат: {error}"

    @registry.tool(
        "network_traceroute",
        "Трассировка маршрута до узла.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "max_hops": {"type": "integer"},
            },
            "required": ["host"],
        },
        category="network",
    )
    def network_traceroute(host, max_hops=30):
        result = run_command(
            ["tracert", "-h", str(int(max_hops or 30)), str(host)],
            timeout=180,
        )
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "network_netstat",
        "Активные сетевые соединения.",
        {
            "type": "object",
            "properties": {
                "state": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="network",
    )
    def network_netstat(state="ESTABLISHED", limit=100):
        lines = []
        for connection in psutil.net_connections(kind="inet"):
            if state and connection.status != state:
                continue
            lines.append(
                f"{connection.laddr} -> {connection.raddr} "
                f"[{connection.status}] pid={connection.pid}"
            )
            if len(lines) >= int(limit or 100):
                break
        return "\n".join(lines) or "Соединений не найдено."

    @registry.tool(
        "network_speedtest",
        "Измерить скорость интернета.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_speedtest():
        speedtest = optional_import("speedtest")
        if speedtest is None:
            return "Для теста скорости установите speedtest-cli."
        try:
            client = speedtest.Speedtest()
            client.get_best_server()
            download = client.download() / 1_000_000
            upload = client.upload() / 1_000_000
            ping = client.results.ping
            return (
                f"Загрузка: {download:.1f} Мбит/с\n"
                f"Отдача: {upload:.1f} Мбит/с\n"
                f"Пинг: {ping:.0f} мс"
            )
        except Exception as error:
            return f"Тест скорости не удался: {error}"

    @registry.tool(
        "network_ssh",
        "Выполнить команду на сервере по SSH.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "command": {"type": "string"},
                "password": {"type": "string"},
                "key_path": {"type": "string"},
                "port": {"type": "integer"},
                "timeout": {"type": "integer"},
            },
            "required": ["host", "username", "command"],
        },
        category="network",
        danger="confirm",
    )
    def network_ssh(
        host,
        username,
        command,
        password=None,
        key_path=None,
        port=22,
        timeout=30,
    ):
        paramiko = optional_import("paramiko")
        if paramiko is None:
            return "Для SSH установите paramiko."
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                str(host),
                port=int(port or 22),
                username=str(username),
                password=password or None,
                key_filename=str(key_path) if key_path else None,
                timeout=float(timeout or 30),
            )
            _, stdout, stderr = client.exec_command(str(command))
            output = stdout.read().decode("utf-8", "replace")
            error = stderr.read().decode("utf-8", "replace")
            return output or error or "Команда выполнена."
        except Exception as error:
            return f"SSH-ошибка: {error}"
        finally:
            client.close()

    @registry.tool(
        "network_sftp",
        "Скачать или загрузить файл по SFTP.",
        {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "key_path": {"type": "string"},
                "remote": {"type": "string"},
                "local": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["upload", "download"],
                },
                "port": {"type": "integer"},
            },
            "required": [
                "host",
                "username",
                "remote",
                "local",
                "direction",
            ],
        },
        category="network",
        danger="confirm",
    )
    def network_sftp(
        host,
        username,
        remote,
        local,
        direction="download",
        password=None,
        key_path=None,
        port=22,
    ):
        paramiko = optional_import("paramiko")
        if paramiko is None:
            return "Для SFTP установите paramiko."
        transport = paramiko.Transport((str(host), int(port or 22)))
        try:
            if key_path:
                key = paramiko.RSAKey.from_private_key_file(str(key_path))
                transport.connect(username=str(username), pkey=key)
            else:
                transport.connect(
                    username=str(username), password=password or ""
                )
            sftp = paramiko.SFTPClient.from_transport(transport)
            local_path = resolve_path(local)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if direction == "upload":
                sftp.put(str(local_path), str(remote))
                return f"Загружено: {local_path} -> {remote}"
            sftp.get(str(remote), str(local_path))
            return f"Скачано: {remote} -> {local_path}"
        except Exception as error:
            return f"SFTP-ошибка: {error}"
        finally:
            transport.close()

    @registry.tool(
        "network_wake_on_lan",
        "Отправить Wake-on-LAN пакет.",
        {
            "type": "object",
            "properties": {
                "mac": {"type": "string"},
                "broadcast": {"type": "string"},
                "port": {"type": "integer"},
            },
            "required": ["mac"],
        },
        category="network",
    )
    def network_wake_on_lan(mac, broadcast="255.255.255.255", port=9):

        cleaned = str(mac).replace(":", "").replace("-", "")
        if len(cleaned) != 12:
            return "Некорректный MAC-адрес."
        payload = b"\xff" * 6 + bytes.fromhex(cleaned) * 16
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (str(broadcast), int(port or 9)))
        finally:
            sock.close()
        return f"Wake-on-LAN отправлен на {mac}."

    @registry.tool(
        "network_shares",
        "Список сетевых ресурсов.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_shares():
        result = run_command(["net", "view"], timeout=30)
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "network_proxy",
        "Показать настройки прокси Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="network",
    )
    def network_proxy():
        return powershell(
            "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
            "| Select-Object ProxyEnable, ProxyServer, AutoConfigURL | "
            "Format-List | Out-String",
            timeout=15,
        )
