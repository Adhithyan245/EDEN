"""Shared test doubles and builders for the memory suite.

Everything here is deterministic and offline: fake LLM providers that implement
the canonical ``stream_reply`` interface, an embedding stub that actually yields
to the event loop (to exercise interleaving), and a ``make_manager`` helper that
wires a real MemoryManager over a temp SQLite file with local embeddings.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.memory.embeddings import LocalHashEmbedding
from app.memory.manager import MemoryManager
from app.memory.retrieval import Retriever
from app.memory.storage import SQLiteStorage
from app.memory.summarizer import Summarizer
from app.memory.updater import MemoryUpdater


class FakeLLM:
    """Yields a fixed payload (dict → JSON, or a raw string) as one delta."""

    name = "fake"

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def stream_reply(self, messages, system, *, model=None, intent=None):
        yield self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


class EmptyMemoryLLM(FakeLLM):
    """Extraction that decides nothing is worth remembering."""

    def __init__(self) -> None:
        super().__init__({"memories": []})


class RaisingLLM:
    """A provider whose stream raises immediately (simulates a provider outage)."""

    name = "raising"

    async def stream_reply(self, messages, system, *, model=None, intent=None):
        raise RuntimeError("simulated provider failure")
        yield  # pragma: no cover — makes this an async generator


class SlowEmbedding:
    """Embedding stub that awaits (yields to the loop) before returning.

    Used to force real task interleaving in concurrency tests, so the
    check-then-act in the updater is exercised under genuine suspension.
    """

    name = "slow-emb"
    dim = 16

    def __init__(self, vector=None) -> None:
        self._vector = vector or ([1.0] + [0.0] * 15)

    async def embed(self, texts):
        await asyncio.sleep(0.005)
        return [list(self._vector) for _ in texts]


class RaisingEmbedding:
    """Embedding provider that always raises (to test retrieval degradation)."""

    name = "raising-emb"
    dim = 8

    async def embed(self, texts):
        raise RuntimeError("embedding backend down")


def make_manager(
    db_path,
    *,
    embeddings=None,
    enabled: bool = True,
    scope: str = "tester",
    max_injected: int = 6,
    min_score: float = 0.05,
    summary_threshold: int = 4,
    retriever: Retriever | None = None,
) -> MemoryManager:
    """Build a real MemoryManager over ``db_path`` with test-friendly defaults."""
    return MemoryManager(
        storage=SQLiteStorage(str(db_path)),
        embeddings=embeddings or LocalHashEmbedding(dim=256),
        retriever=retriever or Retriever(),
        updater=MemoryUpdater(),
        summarizer=Summarizer(),
        scope=scope,
        enabled=enabled,
        max_injected=max_injected,
        min_score=min_score,
        summary_threshold=summary_threshold,
    )
