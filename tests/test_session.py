"""Session persistence and compaction."""

from __future__ import annotations

import os
import stat
import time

import pytest

from vspagent.session import Session, SessionStore


def store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def test_new_session_has_an_id_and_metadata(tmp_path) -> None:
    session = store(tmp_path).new("kimi", "model", "/work")

    assert session.id
    assert session.provider == "kimi"
    assert session.model == "model"
    assert session.cwd == "/work"


def test_save_load_round_trip_and_mode(tmp_path) -> None:
    target_store = store(tmp_path)
    session = target_store.new("kimi", "model", "/work")
    session.append({"role": "user", "content": "hello"})

    path = target_store.save(session)
    loaded = target_store.load(session.id)

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert loaded.messages == session.messages
    assert loaded.title == "hello"


def test_latest_returns_the_most_recent(tmp_path) -> None:
    target_store = store(tmp_path)
    first = target_store.new("kimi", "m", "/a")
    first.updated_at = time.time() - 10
    target_store.save(first)
    second = target_store.new("kimi", "m", "/b")
    target_store.save(second)

    assert target_store.latest().id == second.id
    assert [item.id for item in target_store.list()] == [second.id, first.id]


def test_delete_removes_the_file(tmp_path) -> None:
    target_store = store(tmp_path)
    session = target_store.new("kimi", "m", "/a")
    target_store.save(session)

    assert target_store.delete(session.id) is True
    assert target_store.delete(session.id) is False


def test_invalid_session_id_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        store(tmp_path).load("../escape")


def test_corrupt_session_files_are_skipped(tmp_path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "broken.json").write_text("{not json", encoding="utf-8")

    assert store(tmp_path).list() == []


def test_compact_keeps_recent_messages_and_adds_a_note() -> None:
    session = Session(id="x")
    for index in range(10):
        session.messages.append({"role": "user", "content": str(index)})

    session.compact(keep=4)

    assert len(session.messages) == 5
    assert "compacted" in session.messages[0]["content"]
    assert session.messages[-1]["content"] == "9"


def test_compact_does_not_start_in_the_middle_of_a_tool_sequence() -> None:
    session = Session(id="x")
    session.messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "done"},
    ]

    session.compact(keep=3)

    assert session.messages[1]["role"] == "user"
    assert session.messages[1]["content"] == "next"


def test_usage_accumulates() -> None:
    session = Session(id="x")

    session.add_usage({"prompt_tokens": 3, "completion_tokens": 4})
    session.add_usage({"prompt_tokens": 1, "completion_tokens": 2})

    assert session.usage == {"prompt_tokens": 4, "completion_tokens": 6}
