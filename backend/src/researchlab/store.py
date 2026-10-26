"""SQLite persistence for runs, events and snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .schemas import RunEvent, RunSnapshot, RunStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    agent TEXT,
    task_id TEXT,
    message TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class Store:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        # Runs that were in flight when the process stopped can never finish.
        await self._db.execute(
            "UPDATE runs SET status=?, error=? WHERE status IN (?, ?)",
            (RunStatus.FAILED, "interrupted by server restart", RunStatus.QUEUED, RunStatus.RUNNING),
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "store not opened"
        return self._db

    async def save_snapshot(self, snap: RunSnapshot) -> None:
        await self.db.execute(
            """INSERT INTO runs (id, question, mode, status, created_at, finished_at, error, snapshot_json)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, finished_at=excluded.finished_at,
               error=excluded.error, snapshot_json=excluded.snapshot_json""",
            (
                snap.run_id,
                snap.question,
                snap.mode,
                snap.status,
                snap.created_at.isoformat(),
                snap.finished_at.isoformat() if snap.finished_at else None,
                snap.error,
                snap.model_dump_json(),
            ),
        )
        await self.db.commit()

    async def get_snapshot(self, run_id: str) -> RunSnapshot | None:
        async with self.db.execute("SELECT snapshot_json FROM runs WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
        return RunSnapshot.model_validate_json(row["snapshot_json"]) if row else None

    async def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.db.execute(
            "SELECT id, question, mode, status, created_at, finished_at, error FROM runs "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def append_event(self, ev: RunEvent) -> None:
        await self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (
                ev.run_id,
                ev.seq,
                ev.ts.isoformat(),
                ev.type,
                ev.agent,
                ev.task_id,
                ev.message,
                json.dumps(ev.data, default=str),
            ),
        )
        await self.db.commit()

    async def events_after(self, run_id: str, after: int = 0) -> list[RunEvent]:
        async with self.db.execute(
            "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after)
        ) as cur:
            rows = await cur.fetchall()
        return [
            RunEvent(
                run_id=r["run_id"],
                seq=r["seq"],
                ts=datetime.fromisoformat(r["ts"]),
                type=r["type"],
                agent=r["agent"],
                task_id=r["task_id"],
                message=r["message"],
                data=json.loads(r["data_json"]),
            )
            for r in rows
        ]
