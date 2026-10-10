"""SQLite-backed job metadata store.

Holds lightweight metadata only (status, settings, result summary). Media and
large artifacts (transcript, edit plan) live as files in the job's private
directory. On free hosts the disk is ephemeral, so this survives process
restarts but not container rebuilds — which is fine for a temporary-file demo.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.schemas.jobs import JobStatus
from app.services.state_machine import ACTIVE, assert_transition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    source_json TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    analysis_done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class JobRecord:
    id: str
    status: JobStatus
    progress: float | None
    created_at: str
    updated_at: str
    expires_at: str
    filename: str
    settings: dict[str, Any]
    source: dict[str, Any] | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    cancel_requested: bool
    analysis_done: bool
    token_hash: str

    def token_matches(self, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(self.token_hash, hash_token(token))

    @property
    def is_expired(self) -> bool:
        return datetime.fromisoformat(self.expires_at) <= utcnow()


class JobStore:
    def __init__(self, db_path: Path, ttl_minutes: int):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- creation / lookup -------------------------------------------------
    def create(self, filename: str, settings: dict[str, Any]) -> tuple[JobRecord, str]:
        job_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, token_hash, status, progress, created_at, updated_at, expires_at, filename, settings_json)"
                " VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    hash_token(token),
                    JobStatus.QUEUED.value,
                    iso(now),
                    iso(now),
                    iso(now + self.ttl),
                    filename,
                    json.dumps(settings),
                ),
            )
        rec = self.get(job_id)
        assert rec is not None
        return rec, token

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def all_ids(self) -> set[str]:
        with self._lock:
            return {r["id"] for r in self._conn.execute("SELECT id FROM jobs")}

    def count_active(self) -> int:
        marks = ",".join("?" * len(ACTIVE))
        with self._lock:
            return self._conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE status IN ({marks})", [s.value for s in ACTIVE]
            ).fetchone()[0]

    def active_ids(self) -> list[str]:
        marks = ",".join("?" * len(ACTIVE))
        with self._lock:
            return [
                r["id"] for r in self._conn.execute(f"SELECT id FROM jobs WHERE status IN ({marks})", [s.value for s in ACTIVE])
            ]

    def expired_candidates(self) -> list[str]:
        with self._lock:
            return [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM jobs WHERE expires_at <= ? AND status != ?", (iso(utcnow()), JobStatus.EXPIRED.value)
                )
            ]

    def purge_old(self, older_than: timedelta) -> int:
        """Delete metadata rows of jobs that expired long ago."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM jobs WHERE status = ? AND expires_at <= ?", (JobStatus.EXPIRED.value, iso(utcnow() - older_than))
            )
            return cur.rowcount

    # ---- mutation ----------------------------------------------------------
    def transition(
        self,
        job_id: str,
        new: JobStatus,
        *,
        progress: float | None = None,
        error: tuple[str, str] | None = None,
        force: bool = False,
    ) -> JobRecord:
        with self._lock:
            rec = self.get(job_id)
            if rec is None:
                raise KeyError(job_id)
            if not force:
                assert_transition(rec.status, new)
            fields = {"status": new.value, "progress": progress, "updated_at": iso(utcnow())}
            if error:
                fields["error_code"], fields["error_message"] = error
            elif new in ACTIVE:
                fields["error_code"] = fields["error_message"] = None
            self._update(job_id, fields)
            return self.get(job_id)  # type: ignore[return-value]

    def set_progress(self, job_id: str, progress: float | None) -> None:
        with self._lock:
            self._update(job_id, {"progress": None if progress is None else round(progress, 4)})

    def update(self, job_id: str, **fields: Any) -> None:
        mapping = {}
        for key, value in fields.items():
            if key in ("settings", "source", "result"):
                mapping[f"{key}_json"] = None if value is None else json.dumps(value)
            elif key in ("cancel_requested", "analysis_done"):
                mapping[key] = int(bool(value))
            else:
                mapping[key] = value
        mapping["updated_at"] = iso(utcnow())
        with self._lock:
            self._update(job_id, mapping)

    def extend_expiry(self, job_id: str) -> None:
        with self._lock:
            self._update(job_id, {"expires_at": iso(utcnow() + self.ttl)})

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def _update(self, job_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", [*fields.values(), job_id])

    @staticmethod
    def _row(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            progress=row["progress"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            filename=row["filename"],
            settings=json.loads(row["settings_json"]),
            source=json.loads(row["source_json"]) if row["source_json"] else None,
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            cancel_requested=bool(row["cancel_requested"]),
            analysis_done=bool(row["analysis_done"]),
            token_hash=row["token_hash"],
        )
