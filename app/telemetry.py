import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _disk_root():
    anchor = Path.home().anchor
    return anchor or str(Path.home())


def format_uptime(uptime_seconds):
    seconds = max(0, int(uptime_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} д {hours} ч"

    return f"{hours} ч {minutes} мин"


def snapshot():
    if psutil is None:
        return {
            "available": False,
            "cpu": 0.0,
            "memory": 0.0,
            "disk": 0.0,
            "battery": None,
            "uptime": "—",
        }

    try:
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(_disk_root())
        battery_info = psutil.sensors_battery()

        battery = None
        if battery_info is not None:
            battery = {
                "percent": round(battery_info.percent),
                "plugged": bool(battery_info.power_plugged),
            }

        return {
            "available": True,
            "cpu": round(cpu),
            "memory": round(memory.percent),
            "disk": round(disk.percent),
            "battery": battery,
            "uptime": format_uptime(
                time.time() - psutil.boot_time()
            ),
        }

    except Exception:
        return {
            "available": False,
            "cpu": 0.0,
            "memory": 0.0,
            "disk": 0.0,
            "battery": None,
            "uptime": "—",
        }
