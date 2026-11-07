"""Централизованное логирование JARVIS.

Печатать в stdout из фоновых потоков дорого и неудобно: в оконном
режиме stdout может отсутствовать, а консоль тормозит UI. Поэтому
основной поток логов идёт в ротируемый файл, а консоль подключается
только когда она действительно интерактивная. UI может подписаться
на записи через add_sink().
"""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from app.paths import LOG_DIR

_LOG_FILE = LOG_DIR / "jarvis.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False
_lock = threading.Lock()
_sinks = []


class _SinkHandler(logging.Handler):
    def emit(self, record):
        try:
            message = self.format(record)
        except Exception:
            return
        for sink in tuple(_sinks):
            try:
                sink(record.levelname, message)
            except Exception:
                continue


def add_sink(callback):
    if callback not in _sinks:
        _sinks.append(callback)


def remove_sink(callback):
    try:
        _sinks.remove(callback)
    except ValueError:
        pass


def configure_logging(level=logging.INFO):
    global _configured
    with _lock:
        if _configured:
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        root.setLevel(level)

        formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)

        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        stream = sys.stderr
        if stream is not None and getattr(stream, "isatty", lambda: False)():
            console = logging.StreamHandler(stream)
            console.setFormatter(formatter)
            root.addHandler(console)

        sink_handler = _SinkHandler()
        sink_handler.setFormatter(formatter)
        root.addHandler(sink_handler)

        _configured = True


def get_logger(name):
    configure_logging()
    return logging.getLogger(name)
