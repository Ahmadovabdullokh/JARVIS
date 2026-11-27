"""Автопрофиль производительности и ограничения для слабого железа."""

import pytest

from app import performance


@pytest.fixture(autouse=True)
def clean_profile(monkeypatch):
    monkeypatch.delenv("JARVIS_TIER", raising=False)
    performance.reset_cache()
    yield
    performance.reset_cache()


def fake_hardware(cores, threads, ram_gb):
    return lambda: {
        "cores": cores,
        "threads": threads,
        "ram_gb": ram_gb,
    }


def test_detect_tier_low_for_weak_hardware(monkeypatch):
    monkeypatch.setattr(
        performance,
        "read_hardware",
        fake_hardware(2, 4, 7.8),
    )
    assert performance.detect_tier(force=True) == "low"


def test_detect_tier_standard_for_midrange(monkeypatch):
    monkeypatch.setattr(
        performance,
        "read_hardware",
        fake_hardware(4, 8, 16.0),
    )
    assert performance.detect_tier(force=True) == "standard"


def test_detect_tier_high_for_strong_hardware(monkeypatch):
    monkeypatch.setattr(
        performance,
        "read_hardware",
        fake_hardware(8, 16, 32.0),
    )
    assert performance.detect_tier(force=True) == "high"


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("JARVIS_TIER", "high")
    monkeypatch.setattr(
        performance,
        "read_hardware",
        fake_hardware(2, 4, 7.8),
    )
    assert performance.detect_tier(force=True) == "high"


def test_low_profile_clamps_camera(monkeypatch):
    monkeypatch.setattr(performance, "detect_tier", lambda: "low")
    settings = {
        "stream_fps": 30,
        "analyze_fps": 12,
        "jpeg_quality": 88,
        "sharpness": 0.5,
        "max_clients": 4,
    }

    performance.clamp_camera(settings)

    assert settings == {
        "stream_fps": 12.0,
        "analyze_fps": 8.0,
        "jpeg_quality": 78,
        "sharpness": 0.25,
        "max_clients": 2,
    }


def test_standard_profile_keeps_settings(monkeypatch):
    monkeypatch.setattr(performance, "detect_tier", lambda: "standard")
    settings = {"stream_fps": 30, "num_hands": 2}

    performance.clamp_camera(settings)
    performance.clamp_gestures(settings)

    assert settings == {"stream_fps": 30, "num_hands": 2}


def test_low_profile_clamps_gestures(monkeypatch):
    monkeypatch.setattr(performance, "detect_tier", lambda: "low")
    settings = {"num_hands": 2}

    performance.clamp_gestures(settings)

    assert settings["num_hands"] == 1


def test_low_profile_workers_and_budgets(monkeypatch):
    monkeypatch.setattr(performance, "is_low", lambda: True)

    assert performance.tool_workers() == 3
    assert performance.task_workers() == 2
    assert performance.parallel_workers() == 2
    assert performance.clamp_tool_limit(100) == 40
    assert performance.clamp_tool_limit(25) == 25
    assert performance.category_planning_enabled() is False


def test_bootstrap_payload_has_tier(monkeypatch):
    monkeypatch.setattr(performance, "detect_tier", lambda: "low")
    payload = performance.bootstrap_payload()

    assert payload["tier"] == "low"
    assert payload["ui_lite"] is True
    assert payload["poll_ms"] >= 200
