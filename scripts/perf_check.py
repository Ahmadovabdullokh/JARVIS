"""Замер ключевых показателей JARVIS.

Снимает метрики, которые важны на слабом ноутбуке (i3-10110U, 8 ГБ):
стоимость импорта UI-моста, скорость выдачи UI-событий, батчинг
журнала задач и занятое место на диске.

    python scripts/perf_check.py            # только показать
    python scripts/perf_check.py --save     # обновить baseline
    python scripts/perf_check.py --compare  # сравнить с baseline
"""

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data" / "perf_baseline.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def measure_import(module="app.ui_bridge", runs=3):
    """Время холодного импорта модуля в отдельном процессе, секунды."""

    code = (
        "import time;"
        "start = time.perf_counter();"
        f"import {module};"
        "print(time.perf_counter() - start)"
    )
    samples = []
    for _ in range(runs):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None
        samples.append(float(result.stdout.strip()))
    return round(statistics.median(samples), 3)


def measure_event_bus():
    """Микросекунды на выдачу событий у хвоста и сначала очереди."""

    from app import main as jarvis_main

    for _ in range(20000):
        jarvis_main.publish_ui_event("system", "x" * 200)

    start = time.perf_counter()
    for _ in range(2000):
        jarvis_main.drain_ui_events(19990)
    near_tail = (time.perf_counter() - start) / 2000

    start = time.perf_counter()
    for _ in range(100):
        jarvis_main.drain_ui_events(0)
    full = (time.perf_counter() - start) / 100

    return {
        "drain_near_tail_us": round(near_tail * 1e6, 2),
        "drain_full_queue_ms": round(full * 1e3, 2),
        "buffer_size": len(jarvis_main._UI_EVENTS),
    }


def measure_tasks():
    """Время записи журнала и размер снимка для UI."""

    from app.tasks import TaskManager

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "tasks.json"
        manager = TaskManager(path=path, save_delay=60)
        task_id = manager.create("Замер")
        start = time.perf_counter()
        for index in range(50):
            manager.add_step(task_id, f"Шаг {index}")
        batched = time.perf_counter() - start
        start = time.perf_counter()
        manager.flush()
        flush = time.perf_counter() - start
        journal_kb = path.stat().st_size / 1024
        # 50 задач по 5 шагов — типичный накопленный журнал.
        for index in range(50):
            extra_id = manager.create(f"Задача {index}")
            for step in range(5):
                manager.add_step(extra_id, f"Шаг {step}")
        manager.flush()
        snapshot_kb = len(
            json.dumps(
                manager.summary(limit=50),
                ensure_ascii=False,
            ).encode("utf-8")
        ) / 1024
        manager.shutdown()

    return {
        "add_50_steps_ms": round(batched * 1e3, 2),
        "flush_ms": round(flush * 1e3, 2),
        "journal_kb": round(journal_kb, 1),
        "snapshot_kb": round(snapshot_kb, 1),
    }


def measure_jpeg():
    """Кодирование кадра 640x480 — цена камеры на каждом кадре."""

    try:
        import cv2
        import numpy as np
    except Exception:
        return {"encode_q74_ms": None, "encode_q88_ms": None}

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 1] = np.tile(
        np.arange(640, dtype=np.uint8),
        (480, 1),
    )
    result = {}
    for quality in (74, 88):
        samples = []
        for _ in range(20):
            start = time.perf_counter()
            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, quality],
            )
            samples.append(time.perf_counter() - start)
        result[f"encode_q{quality}_ms"] = round(
            statistics.median(samples) * 1e3, 2
        )
        if ok:
            result[f"size_q{quality}_kb"] = round(len(buffer) / 1024, 1)
    return result


def directory_size(path):
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def measure_disk():
    usage = shutil.disk_usage(ROOT)
    return {
        "free_gb": round(usage.free / (1024 ** 3), 2),
        "data_mb": round(directory_size(ROOT / "data") / (1024 ** 2), 1),
        "dist_mb": round(directory_size(ROOT / "dist") / (1024 ** 2), 1),
    }


def collect():
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "import_ui_bridge_s": measure_import(),
        "event_bus": measure_event_bus(),
        "tasks": measure_tasks(),
        "jpeg": measure_jpeg(),
        "disk": measure_disk(),
    }


def print_report(current, baseline=None):
    flat = {}

    def walk(prefix, value):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else key, item)
        else:
            flat[prefix] = value

    walk("", current)
    for key, value in flat.items():
        line = f"{key:38} {value}"
        if baseline and key in baseline:
            old = baseline[key]
            if isinstance(value, (int, float)) and isinstance(
                old, (int, float)
            ) and old:
                change = (value - old) / old * 100
                line += f"   (было {old}, {change:+.0f}%)"
        print(line)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args(argv)

    current = collect()
    baseline = None
    if args.compare and BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    print_report(current, baseline)

    if args.save:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nBaseline сохранён: {BASELINE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
