import json
from types import SimpleNamespace

import pytest

from app import ui_bridge
from app.ui_bridge import UiBridge, _json_safe


def _patch_snapshot(monkeypatch):
    monkeypatch.setattr(ui_bridge, "get_status", lambda: "ready")
    monkeypatch.setattr(
        ui_bridge,
        "telemetry",
        SimpleNamespace(
            snapshot=lambda: {
                "available": True,
                "cpu": 12,
                "memory": 34,
                "disk": 56,
                "battery": {"percent": 80, "plugged": True},
                "uptime": "1 ч 2 мин",
            }
        ),
    )
    monkeypatch.setattr(
        ui_bridge,
        "get_task_snapshot",
        lambda: [{"id": 1, "status": "running", "title": "Demo"}],
    )
    monkeypatch.setattr(ui_bridge, "get_chat_mode", lambda: "tasks")
    monkeypatch.setattr(
        ui_bridge,
        "transcript_preview_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        ui_bridge.config_module,
        "read_config_file",
        lambda: {
            "agent": {"max_iterations": 12},
            "safety": {},
            "chat_mode": "tasks",
        },
    )
    monkeypatch.setattr(
        ui_bridge.persona,
        "get_time_greeting",
        lambda: "Доброй ночи",
    )


def test_json_safe_handles_nested_values():
    value = {
        "text": "x" * 20,
        "items": [1, None, {"ok": True}],
    }
    result = _json_safe(value, limit=5)
    assert result["text"] == "xxxxx…"
    assert result["items"][2]["ok"] is True


def test_bootstrap_is_json_serializable(monkeypatch):
    _patch_snapshot(monkeypatch)
    bridge = UiBridge()
    data = bridge.bootstrap()
    assert data["status"]["name"] == "ready"
    assert data["telemetry"]["cpu"] == 12
    assert data["tasks"][0]["title"] == "Demo"
    assert data["version"] == "MK X"
    assert data["greeting"] == "Доброй ночи"
    json.dumps(data, ensure_ascii=False)


def test_poll_caches_catalog(monkeypatch):
    _patch_snapshot(monkeypatch)
    catalog = [
        {
            "type": "function",
            "function": {"name": "open_app", "description": "Открыть"},
        }
    ]
    monkeypatch.setattr(
        ui_bridge,
        "drain_ui_events",
        lambda after_seq=0: [
            (1, "command_catalog", catalog),
            (2, "assistant", "Готово"),
        ],
    )
    bridge = UiBridge()
    result = bridge.poll()
    assert result["events"][0]["type"] == "command_catalog"
    assert result["events"][1]["payload"] == "Готово"
    assert bridge.get_catalog()["tools"][0]["function"]["name"] == "open_app"
    json.dumps(result, ensure_ascii=False)


def test_save_settings_updates_config(monkeypatch):
    config = {"agent": {}, "safety": {}, "chat_mode": "tasks"}
    saved = {}
    modes = []
    previews = []
    events = []
    monkeypatch.setattr(
        ui_bridge.config_module,
        "read_config_file",
        lambda: config,
    )
    monkeypatch.setattr(
        ui_bridge.config_module,
        "save_config",
        lambda value: saved.update(value),
    )
    monkeypatch.setattr(
        ui_bridge,
        "set_chat_mode",
        lambda value: modes.append(value) or value,
    )
    monkeypatch.setattr(
        ui_bridge,
        "set_transcript_preview",
        lambda value: previews.append(value),
    )
    monkeypatch.setattr(
        ui_bridge,
        "publish_ui_event",
        lambda event, payload: events.append((event, payload)),
    )
    bridge = UiBridge()
    result = bridge.save_settings(
        {
            "autonomy": "full",
            "chat_mode": "code",
            "confirm_destructive": True,
            "dry_run": False,
            "taint_tracking": True,
            "transcript_preview": True,
            "category_planning": True,
            "max_tools_per_request": 120,
            "code_tools_per_request": 30,
            "max_iterations": 15,
            "max_tokens": 4000,
            "tool_timeout_seconds": 90,
            "stt_noise_adapt_k": 3.5,
            "max_speech_seconds": 10.0,
            "silence_duration": 0.6,
        }
    )
    assert result["message"] == "Настройки сохранены."
    assert saved["agent"]["autonomy"] == "full"
    assert saved["agent"]["max_iterations"] == 15
    assert saved["safety"]["confirm_destructive"] is True
    assert saved["chat_mode"] == "code"
    assert modes == ["code"]
    assert previews == [True]
    assert events


def test_save_settings_rejects_bad_autonomy(monkeypatch):
    monkeypatch.setattr(
        ui_bridge.config_module,
        "read_config_file",
        lambda: {"agent": {}, "safety": {}},
    )
    bridge = UiBridge()
    with pytest.raises(ValueError):
        bridge.save_settings({"autonomy": "root"})


def test_handle_rejects_unknown_method():
    bridge = UiBridge()
    with pytest.raises(ValueError):
        bridge.handle("nope")
