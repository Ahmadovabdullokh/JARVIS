"""Курсорная выдача UI-событий (регрессия для Tk-HUD и веб-клиента)."""

import collections
import itertools

import pytest

from app import main as jarvis_main


@pytest.fixture
def empty_event_bus(monkeypatch):
    events = collections.deque(maxlen=20)
    monkeypatch.setattr(jarvis_main, "_UI_EVENTS", events)
    monkeypatch.setattr(jarvis_main, "_UI_EVENT_SEQ", itertools.count(1))
    return events


def test_drain_returns_only_events_after_cursor(empty_event_bus):
    jarvis_main.publish_ui_event("system", "one")
    jarvis_main.publish_ui_event("system", "two")

    first = jarvis_main.drain_ui_events()
    assert [(seq, kind, payload) for seq, kind, payload in first] == [
        (1, "system", "one"),
        (2, "system", "two"),
    ]

    jarvis_main.publish_ui_event("assistant", "three")
    rest = jarvis_main.drain_ui_events(2)
    assert [(seq, kind, payload) for seq, kind, payload in rest] == [
        (3, "assistant", "three"),
    ]


def test_drain_empty_when_cursor_is_latest(empty_event_bus):
    jarvis_main.publish_ui_event("system", "one")
    assert jarvis_main.drain_ui_events(1) == []


def test_drain_keeps_events_for_multiple_consumers(empty_event_bus):
    jarvis_main.publish_ui_event("assistant", "hello")

    hud = jarvis_main.drain_ui_events(0)
    phone = jarvis_main.drain_ui_events(0)

    assert len(hud) == 1
    assert hud == phone


def test_partials_are_coalesced(empty_event_bus):
    jarvis_main.publish_ui_event("assistant_partial", "при")
    jarvis_main.publish_ui_event("assistant_partial", "привет")
    jarvis_main.publish_ui_event("assistant", "привет, мир")

    assert len(empty_event_bus) == 2
    kinds = [kind for _, kind, _ in jarvis_main.drain_ui_events(0)]
    assert kinds == ["assistant_partial", "assistant"]


def test_coalescing_keeps_other_events(empty_event_bus):
    jarvis_main.publish_ui_event("system", "старт")
    jarvis_main.publish_ui_event("assistant_partial", "a")
    jarvis_main.publish_ui_event("transcript_preview", "слово")
    jarvis_main.publish_ui_event("assistant_partial", "ab")

    payloads = [
        (kind, payload) for _, kind, payload in jarvis_main.drain_ui_events(0)
    ]
    assert payloads == [
        ("system", "старт"),
        ("transcript_preview", "слово"),
        ("assistant_partial", "ab"),
    ]
