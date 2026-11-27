"""Запуск JARVIS в режиме удалённого доступа.

Поднимает обычный backend (голос, LLM, инструменты) через
``UiBridge`` и HTTP-сервер ``app.remote_server`` на localhost.
Доступ снаружи открывает туннель — см. ``scripts/start_tunnel_cf.ps1``.

С флагом ``--hud`` дополнительно открывает обычное окно JARVIS
на этом ПК в том же процессе: оба интерфейса делят один backend
и видят одни и те же события (чат, задачи, журнал).

Запуск: ``python launcher_remote.py [--hud] [--no-hud]``
или ``scripts\\start_remote.ps1``.
"""

import sys
import time

from app import config as config_module
from app.logging import get_logger
from app.paths import ensure_runtime_dirs
from app.remote_server import RemoteServer, write_status
from app.ui_bridge import UiBridge

log = get_logger(__name__)


def _start_tunnel():
    try:
        from app.tunnel import start_auto_tunnel

        manager = start_auto_tunnel()
        if manager is not None:
            log.info("[TUNNEL] Автоподъём туннеля активен.")
        return manager
    except Exception as error:
        log.info(
            f"[TUNNEL] Автоподъём не удался: "
            f"{type(error).__name__}: {error}"
        )
        return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_runtime_dirs()

    hud = "--no-hud" not in argv  # окно на ПК открываем по умолчанию

    bridge = UiBridge()
    config = config_module.read_config_file()
    remote = config.get("remote")
    remote = remote if isinstance(remote, dict) else {}
    host = str(remote.get("host") or "127.0.0.1").strip()
    server = RemoteServer(bridge, host=host)
    server.start()
    bridge.attach_remote(server)
    bridge.start(start_backend=True)

    banner = (
        "\n"
        "========================================\n"
        " J.A.R.V.I.S. — удалённый доступ\n"
        "========================================\n"
        f" локальный адрес: {server.url}\n"
        f" для телефона по Wi-Fi: {server.lan_url or 'выключен'}\n"
        f" токен: config.json -> remote.token "
        f"(см. scripts\\remote_info.ps1)\n"
        f" HUD при запуске: {'да (--hud)' if hud else 'нет (--no-hud)'}\n"
        " туннель: авто (remote.auto_tunnel) или "
        "scripts\\start_tunnel_cf.ps1\n"
        "========================================\n"
    )
    print(banner, flush=True)
    log.info("[REMOTE LAUNCHER] %s", banner.replace("\n", " | "))
    write_status(server)
    tunnel_manager = _start_tunnel()

    if hud:
        try:
            from launcher_web import run_web_ui
        except Exception as error:
            log.info(
                f"[REMOTE LAUNCHER] HUD недоступен: "
                f"{type(error).__name__}: {error}"
            )
            run_web_ui = None
        if run_web_ui is not None:
            try:
                # Блокирует до закрытия окна; в finally моста уже
                # вызывается bridge.shutdown().
                run_web_ui(bridge)
            except Exception as error:
                log.info(
                    f"[REMOTE LAUNCHER] Ошибка HUD: "
                    f"{type(error).__name__}: {error}"
                )
            finally:
                if tunnel_manager is not None:
                    tunnel_manager.stop()
                server.stop()
            return 0

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel_manager is not None:
            tunnel_manager.stop()
        server.stop()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
