import threading

_status = "starting"
_lock = threading.Lock()


def set_status(new_status: str) -> None:
    global _status

    with _lock:
        _status = str(new_status)


def get_status() -> str:
    with _lock:
        return _status