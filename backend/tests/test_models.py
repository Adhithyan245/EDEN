"""Data-model tests: MemoryType coercion and MemoryRecord construction/serialization."""

from __future__ import annotations

from datetime import datetime

from app.memory.models import ExtractedMemory, MemoryRecord, MemoryType


def test_memorytype_coerce_valid():
    assert MemoryType.coerce("preference") is MemoryType.PREFERENCE
    assert MemoryType.coerce(MemoryType.GOAL) is MemoryType.GOAL
    assert MemoryType.coerce("  User_Profile  ") is MemoryType.USER_PROFILE


def test_memorytype_coerce_invalid_defaults_to_fact():
    assert MemoryType.coerce("nonsense") is MemoryType.FACT
    assert MemoryType.coerce(None) is MemoryType.FACT
    assert MemoryType.coerce(123) is MemoryType.FACT


def test_record_create_clamps_importance_and_strips_content():
    high = MemoryRecord.create(MemoryType.FACT, "  hi  ", importance=5.0)
    low = MemoryRecord.create(MemoryType.FACT, "x", importance=-1.0)
    assert high.importance == 1.0
    assert low.importance == 0.0
    assert high.content == "hi"


def test_record_create_sets_id_and_timestamps():
    r = MemoryRecord.create(MemoryType.GOAL, "ship v2")
    assert r.id and isinstance(r.id, str)
    assert isinstance(r.created_at, datetime)
    assert isinstance(r.updated_at, datetime)
    assert r.access_count == 0
    assert r.last_accessed_at is None


def test_record_create_ids_are_unique():
    ids = {MemoryRecord.create(MemoryType.FACT, f"m{i}").id for i in range(100)}
    assert len(ids) == 100


def test_record_to_dict_shape():
    r = MemoryRecord.create(MemoryType.PREFERENCE, "dark mode", importance=0.7, key="pref:theme")
    r.embedding = [0.1, 0.2]
    d = r.to_dict()
    assert d["type"] == "preference"            # enum serialized to string
    assert d["importance"] == 0.7
    assert d["key"] == "pref:theme"
    assert d["embedding"] == [0.1, 0.2]
    # timestamps are ISO strings, parseable back
    datetime.fromisoformat(d["created_at"])
    datetime.fromisoformat(d["updated_at"])


def test_extracted_memory_defaults():
    e = ExtractedMemory(type=MemoryType.FACT, content="c")
    assert e.action == "store"
    assert e.importance == 0.5
    assert e.key is None
