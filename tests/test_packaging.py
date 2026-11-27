"""Сборка и зависимости: версия, тяжёлый стек, запись WAV."""

import importlib.util
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from app.tools import media
from app.tools.base import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("pandas", "matplotlib", "scipy")


def test_version_comes_from_inno_define():
    spec = importlib.util.spec_from_file_location(
        "gen_version", ROOT / "scripts" / "gen_version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    version = module.project_version()
    inno = (ROOT / "packaging" / "jarvis.iss").read_text(encoding="utf-8")

    assert f'#define MyAppVersion "{version}"' in inno
    assert module.version_tuple(version) == (1, 0, 0, 0)


def test_heavy_scientific_packages_are_not_imported():
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            # Заглушка в gestures проверяет наличие matplotlib через
            # try/except и помечена noqa — это не зависимость.
            if "# noqa" in stripped:
                continue
            if any(
                stripped.startswith(f"import {name}")
                or stripped.startswith(f"from {name}")
                for name in FORBIDDEN
            ):
                offenders.append(f"{path}:{number}: {stripped}")
    assert offenders == []


def test_requirements_do_not_pull_heavy_science_stack():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name in FORBIDDEN:
        assert not any(
            line.strip().startswith(name + "=") or
            line.strip().startswith(name + ">")
            for line in text.splitlines()
        )


def test_mediapipe_works_without_matplotlib():
    code = (
        "from app.gestures import _stub_matplotlib\n"
        "_stub_matplotlib()\n"
        "from mediapipe.tasks.python import vision\n"
        "assert vision.HandLandmarker\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_audio_record_writes_wav_without_scipy(tmp_path):
    class FakeSoundDevice:
        def rec(self, frames, samplerate, channels, dtype):
            return np.zeros((frames, 1), dtype=np.int16)

        def wait(self):
            pass

    output = tmp_path / "clip.wav"
    registry = ToolRegistry()
    media.register(registry)
    real_import = media.optional_import

    def fake_import(name):
        if name == "sounddevice":
            return FakeSoundDevice()
        return real_import(name)

    media.optional_import = fake_import
    try:
        result = registry.execute(
            "audio_record",
            {
                "duration": 0.2,
                "path": str(output),
                "rate": 8000,
            },
        )
    finally:
        media.optional_import = real_import

    assert "clip.wav" in result
    with wave.open(str(output), "rb") as clip:
        assert clip.getnchannels() == 1
        assert clip.getsampwidth() == 2
        assert clip.getframerate() == 8000
        assert clip.getnframes() >= 1600
