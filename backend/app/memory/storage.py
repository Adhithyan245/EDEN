"""Storage backends — where memories are persisted.

Callers depend only on the ``StorageBackend`` interface, never on SQLite
directly, so the store can be replaced later (Postgres, Chroma, Qdrant,
Weaviate) without touching retrieval, updating, or the manager. The interface
is deliberately CRUD-plus-list rather than "search": semantic ranking lives in
``retrieval.py`` and operates on candidates the backend returns, which keeps
the backend contract trivial to satisfy for a future vector DB (it can override
``search`` to push ranking down, but is not required to).

The initial ``SQLiteStorage`` keeps everything in one table and does ranking in
Python — correct and simple at demo/single-user scale. Vectors are stored as
JSON; a vector DB backend would store them natively instead.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import MemoryRecord, MemoryType

log = logging.getLogger("eden.memory.storage")


class StorageBackend(ABC):
    """The persistence contract every backend must satisfy."""

    @abstractmethod
    def add(self, record: MemoryRecord) -> None: ...

    @abstractmethod
    def get(self, id: str) -> Optional[MemoryRecord]: ...

    @abstractmethod
    def get_by_key(self, scope: str, key: str) -> Optional[MemoryRecord]: ...

    @abstractmethod
    def update(self, record: MemoryRecord) -> None: ...

    @abstractmethod
    def delete(self, id: str) -> None: ...

    @abstractmethod
    def list(self, scope: str, types: Optional[list[MemoryType]] = None) -> list[MemoryRecord]:
        """Return all records in ``scope`` (optionally filtered by type).

        This is the candidate set the retriever ranks. A future vector backend
        may narrow it via ANN; the SQLite backend returns everything in scope.
        """

    @abstractmethod
    def touch(self, id: str, when: datetime) -> None:
        """Record an access (bump count + last_accessed_at) for recency/usage stats."""

    @abstractmethod
    def count(self, scope: Optional[str] = None) -> int: ...


class SQLiteStorage(StorageBackend):
    """Single-file SQLite backend. Durable across restarts; thread-safe via a lock.

    Opened with ``check_same_thread=False`` and guarded by a lock so it is safe
    whether called on the event-loop thread or from a run_in_executor worker.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS memories (
        id               TEXT PRIMARY KEY,
        type             TEXT NOT NULL,
        content          TEXT NOT NULL,
        importance       REAL NOT NULL,
        key              TEXT,
        scope            TEXT NOT NULL,
        metadata         TEXT NOT NULL,
        embedding        TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        last_accessed_at TEXT,
        access_count     INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
    CREATE INDEX IF NOT EXISTS idx_memories_scope_key ON memories(scope, key);
    CREATE INDEX IF NOT EXISTS idx_memories_scope_type ON memories(scope, type);
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        # ":memory:" is a special sqlite target, not a filesystem path — don't
        # try to create a parent directory for it (also avoids odd Windows
        # handling of the colon).
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self._SCHEMA)
            self._conn.commit()
        log.info("memory store ready at %s", self._path)

    def close(self) -> None:
        """Close the underlying connection. Safe to call more than once.

        Not needed for the long-lived server process (the OS reclaims the handle
        on exit), but lets tests and any future short-lived user release the
        SQLite file promptly — important on Windows, where an open handle keeps
        the file locked against deletion.
        """
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    # -- writes ----------------------------------------------------------

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, type, content, importance, key, scope, metadata, embedding,
                    created_at, updated_at, last_accessed_at, access_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._to_row(record),
            )
            self._conn.commit()

    def update(self, record: MemoryRecord) -> None:
        # INSERT OR REPLACE keyed on the primary key is a clean upsert here.
        self.add(record)

    def delete(self, id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (id,))
            self._conn.commit()

    def touch(self, id: str, when: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                (when.isoformat(), id),
            )
            self._conn.commit()

    # -- reads -----------------------------------------------------------

    def get(self, id: str) -> Optional[MemoryRecord]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (id,)).fetchone()
        return self._from_row(row) if row else None

    def get_by_key(self, scope: str, key: str) -> Optional[MemoryRecord]:
        if not key:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE scope = ? AND key = ? ORDER BY updated_at DESC LIMIT 1",
                (scope, key),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, scope: str, types: Optional[list[MemoryType]] = None) -> list[MemoryRecord]:
        sql = "SELECT * FROM memories WHERE scope = ?"
        params: list = [scope]
        if types:
            placeholders = ",".join("?" for _ in types)
            sql += f" AND type IN ({placeholders})"
            params.extend(t.value for t in types)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._from_row(r) for r in rows]

    def count(self, scope: Optional[str] = None) -> int:
        with self._lock:
            if scope is None:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM memories WHERE scope = ?", (scope,)
                ).fetchone()
        return int(row["n"]) if row else 0

    # -- row mapping -----------------------------------------------------

    @staticmethod
    def _to_row(r: MemoryRecord) -> tuple:
        return (
            r.id,
            r.type.value,
            r.content,
            r.importance,
            r.key,
            r.scope,
            json.dumps(r.metadata),
            json.dumps(r.embedding) if r.embedding is not None else None,
            r.created_at.isoformat(),
            r.updated_at.isoformat(),
            r.last_accessed_at.isoformat() if r.last_accessed_at else None,
            r.access_count,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id               = row["id"],
            type             = MemoryType.coerce(row["type"]),
            content          = row["content"],
            importance       = row["importance"],
            key              = row["key"],
            scope            = row["scope"],
            metadata         = json.loads(row["metadata"]) if row["metadata"] else {},
            embedding        = json.loads(row["embedding"]) if row["embedding"] else None,
            created_at       = _parse_dt(row["created_at"]),
            updated_at       = _parse_dt(row["updated_at"]),
            last_accessed_at = _parse_dt(row["last_accessed_at"]),
            access_count     = row["access_count"],
        )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
