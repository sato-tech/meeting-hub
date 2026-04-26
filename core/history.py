"""SQLite ベースのジョブ履歴。

スキーマ:
  jobs(id TEXT PK, run_id TEXT UNIQUE, user_id TEXT, cassette TEXT, input_name TEXT,
       status TEXT, started_at TIMESTAMP, finished_at TIMESTAMP, work_dir TEXT, meta_json TEXT)
  step_events(id INT PK AUTOINC, job_id TEXT FK, step TEXT, event TEXT,
              at TIMESTAMP, detail_json TEXT)

DB 配置:
  env `MEETING_HUB_HISTORY_DB` で上書き可。既定 `~/.meeting-hub/history.db`
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def default_db_path() -> Path:
    raw = os.environ.get("MEETING_HUB_HISTORY_DB")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".meeting-hub" / "history.db"


JobStatus = str  # "pending" | "running" | "completed" | "failed" | "cancelled"


@dataclass
class JobRecord:
    id: str
    run_id: str
    user_id: str
    cassette: str
    input_name: str
    status: JobStatus
    started_at: str
    finished_at: str | None
    work_dir: str
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            user_id=row["user_id"],
            cassette=row["cassette"],
            input_name=row["input_name"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            work_dir=row["work_dir"],
            meta=json.loads(row["meta_json"] or "{}"),
        )


class JobHistory:
    """SQLite ジョブ履歴の低レベル API。"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            # WAL モードで同時読み/書きを許容
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    run_id TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL,
                    cassette TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    finished_at TIMESTAMP,
                    work_dir TEXT NOT NULL,
                    meta_json TEXT
                );
                CREATE TABLE IF NOT EXISTS step_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    event TEXT NOT NULL,
                    at TIMESTAMP NOT NULL,
                    detail_json TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_job ON step_events(job_id);
                """
            )

    # ─── Job ────────────────────────────────
    def create(
        self,
        *,
        run_id: str,
        user_id: str,
        cassette: str,
        input_name: str,
        work_dir: str,
        meta: dict[str, Any] | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, run_id, user_id, cassette, input_name, status, "
                "started_at, finished_at, work_dir, meta_json) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?)",
                (job_id, run_id, user_id, cassette, input_name, now, work_dir,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
        return job_id

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        meta: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> None:
        fin_at = datetime.now(UTC).isoformat(timespec="seconds") if finished else None
        with self._connect() as conn:
            if meta is not None:
                conn.execute(
                    "UPDATE jobs SET status=?, finished_at=COALESCE(?, finished_at), "
                    "meta_json=? WHERE id=?",
                    (status, fin_at, json.dumps(meta, ensure_ascii=False), job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status=?, finished_at=COALESCE(?, finished_at) WHERE id=?",
                    (status, fin_at, job_id),
                )

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return JobRecord.from_row(row) if row else None

    def get_by_run_id(self, run_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE run_id=?", (run_id,)).fetchone()
        return JobRecord.from_row(row) if row else None

    def list(
        self, *, user_id: str | None = None, limit: int = 50, include_all: bool = False
    ) -> list[JobRecord]:
        q = "SELECT * FROM jobs"
        params: list[Any] = []
        if user_id and not include_all:
            q += " WHERE user_id=?"
            params.append(user_id)
        q += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
        return [JobRecord.from_row(r) for r in rows]

    def delete(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    # ─── Step Event ──────────────────────────
    def log_event(
        self,
        job_id: str,
        step: str,
        event: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO step_events (job_id, step, event, at, detail_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, step, event, at, json.dumps(detail or {}, ensure_ascii=False)),
            )

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT step, event, at, detail_json FROM step_events "
                "WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [
            {
                "step": r["step"],
                "event": r["event"],
                "at": r["at"],
                "detail": json.loads(r["detail_json"] or "{}"),
            }
            for r in rows
        ]
