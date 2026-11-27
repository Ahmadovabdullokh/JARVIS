"""Батчинг записи журнала задач (регрессия на лишние перезаписи)."""

import json
import time

import pytest

from app.tasks import TaskManager


@pytest.fixture
def manager(tmp_path):
    return TaskManager(
        path=tmp_path / "tasks.json",
        save_delay=60,
    )


def count_writes(manager):
    writes = []
    original = manager._write

    def wrapper():
        result = original()
        writes.append(result)
        return result

    manager._write = wrapper
    return writes


def disk_tasks(manager):
    return json.loads(manager.path.read_text(encoding="utf-8"))


def test_steps_are_batched_between_flushes(manager):
    task_id = manager.create("Пакет")
    writes = count_writes(manager)

    for index in range(50):
        manager.add_step(task_id, f"Шаг {index}")

    # За 50 шагов — ни одной записи: всё ждёт таймера.
    assert writes == []

    manager.flush()

    assert len(writes) == 1
    on_disk = disk_tasks(manager)
    assert len(on_disk[task_id]["steps"]) == 50


def test_timer_writes_without_explicit_flush(tmp_path):
    manager = TaskManager(
        path=tmp_path / "tasks.json",
        save_delay=0.05,
    )
    task_id = manager.create("Таймер")
    manager.add_step(task_id, "Шаг")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if task_id in disk_tasks(manager):
            steps = disk_tasks(manager)[task_id]["steps"]
            if steps:
                break
        time.sleep(0.02)
    else:
        pytest.fail("Таймер не сохранил журнал")

    assert disk_tasks(manager)[task_id]["steps"][0]["title"] == "Шаг"


def test_final_status_is_flushed_immediately(manager):
    task_id = manager.create("Финал")
    writes = count_writes(manager)
    manager.add_step(task_id, "Шаг")
    assert writes == []

    manager.complete(task_id, "готово")

    assert len(writes) == 1
    on_disk = disk_tasks(manager)
    assert on_disk[task_id]["status"] == "done"
    assert on_disk[task_id]["result"] == "готово"


def test_cancel_all_writes_once(manager):
    ids = [manager.create(f"Задача {index}") for index in range(3)]
    for task_id in ids:
        manager.add_step(task_id, "Шаг")

    writes = count_writes(manager)
    manager.cancel_all()

    assert len(writes) == 1
    on_disk = disk_tasks(manager)
    assert all(on_disk[task_id]["status"] == "cancelled" for task_id in ids)


def test_flush_is_noop_when_nothing_changed(manager):
    manager.create("Пусто")
    manager.flush()
    writes = count_writes(manager)

    manager.flush()

    assert writes == []
