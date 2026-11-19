import ctypes
import json
import os
import sys
import threading
import time

from app.logging import get_logger
from app.paths import DATA_DIR, ensure_runtime_dirs, resource_path

log = get_logger(__name__)


def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _screen_size():
    try:
        width = ctypes.windll.user32.GetSystemMetrics(0)
        height = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        width, height = 1440, 900
    return width, height


def _window_geometry():
    screen_w, screen_h = _screen_size()
    width = min(1440, max(1000, screen_w - 100))
    height = min(920, max(640, screen_h - 100))
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2 - 24)
    return width, height, x, y


def _find_hwnd(timeout=5.0):
    import win32gui
    import win32process

    pid = os.getpid()
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def _cb(hwnd, _param):
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid and win32gui.GetWindowTextLength(hwnd):
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if found:
            return found[0]
        time.sleep(0.1)
    return 0


class JarvisBridgeApi:
    """pywebview js_api: exposes rpc() to the HUD page.

    Every request arrives as a JSON string and is answered with a JSON
    string, so the frontend protocol stays identical to the old bridge.
    """

    def __init__(self, bridge, smoke=False):
        self._bridge = bridge
        self._smoke = smoke
        self._window = None
        self._tray = None
        self._runtime_started = False
        self._services_started = False
        self._quitting = False

    def _attach_window(self, window):
        self._window = window
        try:
            window.events.loaded += self._on_loaded
        except Exception:
            pass

    def _on_loaded(self):
        self._start_runtime()
        threading.Thread(
            target=self._place_window,
            name="JARVIS-Place",
            daemon=True,
        ).start()

    def _place_window(self):
        _width, _height, x, y = _window_geometry()
        hwnd = _find_hwnd()
        if hwnd:
            try:
                import win32gui

                win32gui.SetWindowPos(
                    hwnd,
                    0,
                    x,
                    y,
                    0,
                    0,
                    0x0001 | 0x0004,
                )
            except Exception:
                pass

    def _start_runtime(self):
        if self._runtime_started:
            return
        self._runtime_started = True
        log.info("[WEB LAUNCHER] WebView2 window ready.")
        if self._smoke:
            threading.Timer(3.0, self.quit_app).start()

    def _start_services(self):
        if self._services_started:
            return
        self._services_started = True
        log.info("[WEB LAUNCHER] Starting JARVIS services.")
        self._bridge.start(start_backend=not self._smoke)
        threading.Thread(
            target=self._start_tray,
            name="JARVIS-Tray",
            daemon=True,
        ).start()

    def rpc(self, request_json):
        try:
            data = json.loads(request_json)
        except Exception:
            return "{}"
        if not isinstance(data, dict):
            return "{}"
        response = self._handle_request(data)
        try:
            text = json.dumps(
                response,
                ensure_ascii=False,
                default=str,
            )
        except Exception:
            return "{}"
        if data.get("method") != "poll":
            log.info(
                f"[WEB RPC] {data.get('method')}: {len(text)} chars"
            )
        return text

    def _handle_request(self, data):
        request_id = data.get("id")
        method = str(data.get("method", ""))
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if method in {"bootstrap", "client_ready"}:
            log.info(f"[WEB BRIDGE] {method} requested.")
        try:
            if method == "window_action":
                result = self._window_action(payload)
            else:
                result = self._bridge.handle(method, payload)
            response = {
                "type": "jarvis_response",
                "id": request_id,
                "ok": True,
                "data": result,
            }
        except Exception as error:
            log.info(
                f"[WEB BRIDGE] {method}: "
                f"{type(error).__name__}: {error}"
            )
            response = {
                "type": "jarvis_response",
                "id": request_id,
                "ok": False,
                "error": str(error),
            }
        if (
            method in {"bootstrap", "client_ready"}
            and not self._services_started
        ):
            threading.Timer(0.2, self._start_services).start()
        return response

    def _window_action(self, payload):
        import win32con
        import win32gui

        action = str(payload.get("action", ""))
        hwnd = _find_hwnd()
        if action == "hide" and hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        elif action == "minimize" and hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        elif action == "maximize" and hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif action == "restore" and hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        elif action == "quit":
            self.quit_app()
        else:
            raise ValueError(
                f"Неизвестное действие окна: {action}"
            )
        return {"action": action}

    def hide_window(self):
        import win32con
        import win32gui

        hwnd = _find_hwnd()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return {"hidden": True}

    def show_window(self):
        import win32con
        import win32gui

        hwnd = _find_hwnd()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        return {"shown": True}

    def quit_app(self):
        self._quitting = True
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        return {"closing": True}

    def _start_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return
        hwnd = _find_hwnd()
        if not hwnd:
            return
        try:
            image = Image.new("RGB", (64, 64), "#03060d")
            draw = ImageDraw.Draw(image)
            draw.ellipse(
                (8, 8, 56, 56),
                outline="#2ee6ff",
                width=3,
            )
            draw.ellipse((22, 22, 42, 42), fill="#2ee6ff")
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Показать",
                    lambda *_args: self.show_window(),
                ),
                pystray.MenuItem(
                    "Скрыть",
                    lambda *_args: self.hide_window(),
                ),
                pystray.MenuItem(
                    "Стоп",
                    lambda *_args: self._bridge.stop(),
                ),
                pystray.MenuItem(
                    "Выход",
                    lambda *_args: self.quit_app(),
                ),
            )
            self._tray = pystray.Icon(
                "JARVIS",
                image,
                "JARVIS",
                menu,
            )
            self._tray.run()
        except Exception as error:
            log.info(f"[TRAY] {error}")

    def stop_tray(self):
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke" in argv
    debug = "--debug" in argv
    if debug:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--remote-debugging-port=9222"
        )

    ensure_runtime_dirs()
    _enable_dpi_awareness()

    try:
        import pythonnet

        runtime_config = DATA_DIR / "dotnet.runtimeconfig.json"
        if not runtime_config.exists():
            runtime_config.write_text(
                json.dumps(
                    {
                        "runtimeOptions": {
                            "tfm": "net10.0",
                            "frameworks": [
                                {
                                    "name": "Microsoft.NETCore.App",
                                    "version": "10.0.0",
                                },
                                {
                                    "name": "Microsoft.WindowsDesktop.App",
                                    "version": "10.0.0",
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
        pythonnet.load(
            "coreclr",
            runtime_config=str(runtime_config),
        )
    except Exception:
        pass

    try:
        import webview

        from app.ui_bridge import UiBridge
    except Exception as error:
        log.info(
            f"[WEB LAUNCHER] WebView2 недоступен: "
            f"{type(error).__name__}: {error}"
        )
        from launcher import run_tk

        return run_tk()

    cache = DATA_DIR / ("webview2-debug" if debug else "webview2")
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(cache))

    ui_file = resource_path("ui", "index.html")
    if not ui_file.exists():
        log.info("[WEB LAUNCHER] ui/index.html не найден.")
        from launcher import run_tk

        return run_tk()

    width, height, x, y = _window_geometry()
    bridge = UiBridge()
    api = JarvisBridgeApi(bridge, smoke=smoke)

    try:
        window = webview.create_window(
            "J.A.R.V.I.S. — Just A Rather Very Intelligent System",
            ui_file.as_uri(),
            js_api=api,
            width=width,
            height=height,
            min_size=(1000, 640),
        )
    except Exception as error:
        log.info(
            f"[WEB LAUNCHER] Ошибка окна: "
            f"{type(error).__name__}: {error}"
        )
        bridge.shutdown()
        from launcher import run_tk

        return run_tk()

    api._attach_window(window)

    try:
        webview.start(private_mode=False)
    except Exception as error:
        log.info(
            f"[WEB LAUNCHER] Ошибка GUI: "
            f"{type(error).__name__}: {error}"
        )
        bridge.shutdown()
        api.stop_tray()
        from launcher import run_tk

        return run_tk()
    finally:
        bridge.shutdown()
        api.stop_tray()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
