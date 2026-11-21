"""Изоляция тестов от реального каталога data/.

Переменные окружения выставляются до импорта app.*, поэтому
логи, задания и память тестов не попадают в рабочий data/.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="jarvis-tests-"))
os.environ.setdefault("JARVIS_DATA_DIR", str(_TMP_ROOT / "data"))
os.environ.setdefault("JARVIS_LOG_DIR", str(_TMP_ROOT / "logs"))


@pytest.fixture(scope="session", autouse=True)
def _cleanup_temp_data():
    yield
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
