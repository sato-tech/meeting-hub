"""JobHistory SQLite ラッパのテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.history import JobHistory, JobRecord


@pytest.fixture
def history(tmp_path: Path) -> JobHistory:
    return JobHistory(db_path=tmp_path / "h.db")


def test_create_and_get(history: JobHistory) -> None:
    jid = history.create(
        run_id="20260423_000000_x",
        user_id="alice",
        cassette="sales_meeting",
        input_name="x.mp4",
        work_dir="/tmp/out/x",
        meta={"source": "upload"},
    )
    rec = history.get(jid)
    assert rec is not None
    assert rec.user_id == "alice"
    assert rec.status == "pending"
    assert rec.meta["source"] == "upload"


def test_update_status_and_finished(history: JobHistory) -> None:
    jid = history.create(
        run_id="r1", user_id="alice", cassette="c", input_name="i", work_dir="/tmp", meta={}
    )
    history.update_status(jid, "running")
    assert history.get(jid).status == "running"
    history.update_status(jid, "completed", finished=True, meta={"ok": True})
    rec = history.get(jid)
    assert rec.status == "completed"
    assert rec.finished_at is not None
    assert rec.meta["ok"] is True


def test_list_filters_by_user(history: JobHistory) -> None:
    for u in ("alice", "bob"):
        history.create(run_id=f"r-{u}", user_id=u, cassette="c", input_name="i", work_dir="/", meta={})
    alice_jobs = history.list(user_id="alice")
    bob_jobs = history.list(user_id="bob")
    assert {j.user_id for j in alice_jobs} == {"alice"}
    assert {j.user_id for j in bob_jobs} == {"bob"}

    all_jobs = history.list(include_all=True)
    assert len(all_jobs) == 2


def test_events(history: JobHistory) -> None:
    jid = history.create(run_id="r", user_id="u", cassette="c", input_name="i", work_dir="/", meta={})
    history.log_event(jid, "preprocess", "start")
    history.log_event(jid, "preprocess", "end", detail={"elapsed": 1.2})
    events = history.list_events(jid)
    assert len(events) == 2
    assert events[0]["event"] == "start"
    assert events[1]["detail"]["elapsed"] == 1.2


def test_delete_cascades_events(history: JobHistory) -> None:
    jid = history.create(run_id="r", user_id="u", cassette="c", input_name="i", work_dir="/", meta={})
    history.log_event(jid, "preprocess", "start")
    history.delete(jid)
    assert history.get(jid) is None
    assert history.list_events(jid) == []


def test_get_by_run_id(history: JobHistory) -> None:
    jid = history.create(run_id="unique-run-xyz", user_id="u", cassette="c", input_name="i", work_dir="/", meta={})
    rec = history.get_by_run_id("unique-run-xyz")
    assert rec is not None
    assert rec.id == jid
