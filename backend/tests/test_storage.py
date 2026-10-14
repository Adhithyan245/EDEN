"""Storage tests: CRUD, keys, scoping, touch, persistence, corrupt/empty DBs."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.memory.models import MemoryRecord, MemoryType
from app.memory.storage import SQLiteStorage


@pytest.fixture()
def store(tmp_path):
    s = SQLiteStorage(tmp_path / "mem.db")
    yield s
    s.close()  # release the file handle so Windows can delete the temp dir


def _rec(content="hello", type=MemoryType.FACT, key=None, scope="s", importance=0.5, emb=None):
    r = MemoryRecord.create(type, content, importance=importance, key=key, scope=scope)
    r.embedding = emb
    return r


def test_add_and_get_roundtrip(store):
    r = _rec(emb=[0.1, 0.2, 0.3])
    r.metadata = {"source": "test"}
    store.add(r)
    got = store.get(r.id)
    assert got is not None
    assert got.content == "hello"
    assert got.embedding == [0.1, 0.2, 0.3]
    assert got.metadata == {"source": "test"}
    assert got.type is MemoryType.FACT


def test_get_missing_returns_none(store):
    assert store.get("nope") is None


def test_get_by_key(store):
    r = _rec(key="profile:name", scope="s")
    store.add(r)
    assert store.get_by_key("s", "profile:name").id == r.id
    assert store.get_by_key("s", "missing") is None
    assert store.get_by_key("other", "profile:name") is None


def test_get_by_key_returns_latest(store):
    older = _rec(content="old", key="k", scope="s")
    older.updated_at = datetime(2020, 1, 1)
    newer = _rec(content="new", key="k", scope="s")
    newer.updated_at = datetime(2024, 1, 1)
    store.add(older)
    store.add(newer)
    assert store.get_by_key("s", "k").content == "new"


def test_update_overwrites_same_id(store):
    r = _rec(content="v1")
    store.add(r)
    r.content = "v2"
    store.update(r)
    assert store.get(r.id).content == "v2"
    assert store.count("s") == 1


def test_delete(store):
    r = _rec()
    store.add(r)
    store.delete(r.id)
    assert store.get(r.id) is None


def test_list_scope_and_type_filter(store):
    store.add(_rec(content="a", type=MemoryType.FACT, scope="s"))
    store.add(_rec(content="b", type=MemoryType.GOAL, scope="s"))
    store.add(_rec(content="c", type=MemoryType.FACT, scope="other"))
    assert len(store.list("s")) == 2
    assert len(store.list("s", types=[MemoryType.FACT])) == 1
    assert store.list("s", types=[MemoryType.FACT])[0].content == "a"
    assert len(store.list("empty")) == 0


def test_touch_updates_access_stats(store):
    r = _rec()
    store.add(r)
    store.touch(r.id, datetime(2023, 5, 5))
    store.touch(r.id, datetime(2023, 5, 6))
    got = store.get(r.id)
    assert got.access_count == 2
    assert got.last_accessed_at == datetime(2023, 5, 6)


def test_count_scope_vs_all(store):
    store.add(_rec(scope="s"))
    store.add(_rec(scope="s"))
    store.add(_rec(scope="other"))
    assert store.count("s") == 2
    assert store.count() == 3


def test_empty_database(tmp_path):
    s = SQLiteStorage(tmp_path / "empty.db")
    assert s.count() == 0
    assert s.list("anything") == []
    s.close()


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "persist.db"
    s1 = SQLiteStorage(path)
    r = _rec(content="durable", key="k", scope="s", emb=[1.0])
    s1.add(r)
    s1.close()

    s2 = SQLiteStorage(path)
    got = s2.get_by_key("s", "k")
    assert got is not None and got.content == "durable" and got.embedding == [1.0]
    s2.close()


def test_close_is_idempotent(tmp_path):
    s = SQLiteStorage(tmp_path / "c.db")
    s.close()
    s.close()  # must not raise


def test_zero_byte_file_is_treated_as_new_db(tmp_path):
    path = tmp_path / "zero.db"
    path.write_bytes(b"")
    s = SQLiteStorage(path)  # SQLite initializes an empty file fine
    assert s.count() == 0
    s.close()


def test_corrupt_file_raises_databaseerror(tmp_path):
    # Documents the raw backend behavior; build_memory_manager wraps this so a
    # corrupt file degrades to disabled rather than crashing (see test_integration).
    import sqlite3

    path = tmp_path / "corrupt.db"
    path.write_bytes(b"definitely not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        SQLiteStorage(path)
