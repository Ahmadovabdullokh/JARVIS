"""Запуск JARVIS в режиме удалённого доступа.

Поднимает обычный backend (голос, LLM, инструменты) через
``UiBridge`` и HTTP-сервер ``app.remote_server`` на localhost.
Доступ снаружи открывает туннель — см. ``scripts/start_tunnel.ps1``.

С флагом ``--hud`` дополнительно открывает обычное окно JARVIS
на этом ПК в том же процессе: оба интерфейса делят один backend
и видят одни и те же события (чат, задачи, журнал).

Запуск: ``python launcher_remote.py [--hud] [--no-hud]``
или ``scripts\\start_remote.ps1``.
"""

import json
import sys
import time

from app.logging import get_logger
from app.paths import DATA_DIR, ensure_runtime_dirs
from app.remote_server import RemoteServer
from app.ui_bridge import UiBridge

log = get_logger(__name__)

STATUS_FILE = DATA_DIR / "remote_status.json"


def _write_status(url):
    try:
        STATUS_FILE.write_text(
            json.dumps(
                {"url": url, "updated": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_runtime_dirs()

    hud = "--no-hud" not in argv  # окно на ПК открываем по умолчанию

    bridge = UiBridge()
    server = RemoteServer(bridge)
    server.start()
    bridge.start(start_backend=True)

    banner = (
        "\n"
        "========================================\n"
        " J.A.R.V.I.S. — удалённый режим\n"
        "========================================\n"
        f" Локальный адрес: {server.url}\n"
        f" Окно на ПК: {'да (--hud)' if hud else 'нет (--no-hud)'}\n"
        " Туннель: запустите scripts\\start_tunnel.ps1\n"
        "========================================\n"
    )
    print(banner, flush=True)
    log.info("[REMOTE LAUNCHER] %s", banner.replace("\n", " | "))
    _write_status(server.url)

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
                server.stop()
            return 0

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
