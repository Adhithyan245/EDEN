"""MemoryManager — the single facade the rest of EDEN talks to.

The conversation pipeline touches memory through exactly two calls:

    await MEMORY.retrieve_context(user_text)      # before the LLM
    MEMORY.remember_turn(...)  (fire-and-forget)  # after the response

Everything else — embeddings, storage, ranking, the decision stage,
summarization — is wired together here and hidden behind this class. The
manager is provider-agnostic: it holds no LLM, and the caller passes whichever
``LLMProvider`` is active into the update calls, so Gemini / MockLLM /
ScriptedLLM / future providers all use the identical memory layer.

Safety: every public method is fully guarded. If memory is disabled, or any
sub-component raises, retrieval returns an empty string and updates quietly do
nothing — the conversation is never blocked or broken by memory.

Isolation: this subsystem never imports builder, editor, research, events, or
the tool registry, and never emits events. It only reads/writes its own store.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .embeddings import EmbeddingProvider, build_embedding_provider
from .models import ExtractedMemory, MemoryRecord, MemoryType, RetrievedMemory
from .retrieval import Retriever, cosine
from .storage import SQLiteStorage, StorageBackend
from .summarizer import Summarizer
from .updater import MemoryUpdater

if TYPE_CHECKING:
    from ..providers.base import LLMProvider

log = logging.getLogger("eden.memory.manager")

# Above this cosine similarity, two same-type memories are considered the same
# thing and folded into an update rather than stored as a duplicate.
_DEDUP_THRESHOLD = 0.92


class MemoryManager:
    """Coordinates storage, embeddings, retrieval, updating, and summarizing."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        embeddings: EmbeddingProvider,
        retriever: Retriever,
        updater: MemoryUpdater,
        summarizer: Summarizer,
        scope: str = "global",
        enabled: bool = True,
        max_injected: int = 6,
        min_score: float = 0.15,
        summary_threshold: int = 20,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._retriever = retriever
        self._updater = updater
        self._summarizer = summarizer
        self._scope = scope
        self._enabled = enabled
        self._max_injected = max_injected
        self._min_score = min_score
        self._summary_threshold = summary_threshold

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Retrieval (called before the LLM)
    # ------------------------------------------------------------------

    async def retrieve(self, query: str, *, scope: Optional[str] = None) -> list[RetrievedMemory]:
        """Return the top relevant memories for ``query`` (empty on any issue)."""
        if not self._enabled or not query.strip():
            return []
        scope = scope or self._scope
        try:
            candidates = self._storage.list(scope)
            if not candidates:
                return []
            query_embedding = (await self._embeddings.embed([query]))[0]
            ranked = self._retriever.rank(
                query_embedding,
                query,
                candidates,
                now=datetime.utcnow(),
                limit=self._max_injected,
                min_score=self._min_score,
            )
            now = datetime.utcnow()
            for r in ranked:
                self._storage.touch(r.record.id, now)
            if ranked:
                log.info("memory: injected %d/%d memories for query", len(ranked), len(candidates))
            return ranked
        except Exception as exc:  # noqa: BLE001
            log.warning("memory retrieval failed (%s); proceeding with none", exc)
            return []

    async def retrieve_context(self, query: str, *, scope: Optional[str] = None) -> str:
        """Return a prompt-ready memory block for ``query`` ("" when nothing relevant)."""
        ranked = await self.retrieve(query, scope=scope)
        return self.format_for_prompt(ranked)

    @staticmethod
    def format_for_prompt(ranked: list[RetrievedMemory]) -> str:
        """Render retrieved memories as a compact, appendable system-prompt block."""
        if not ranked:
            return ""
        lines = [
            "\n\n[EDEN MEMORY — things you already know about this person and their work.",
            "Draw on these naturally where relevant. Never read this list aloud, never",
            "mention that you have a memory system, never dump it back verbatim.]",
        ]
        for r in ranked:
            lines.append(f"- ({r.record.type.value}) {r.record.content}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Update (called after the response; safe to fire-and-forget)
    # ------------------------------------------------------------------

    async def remember_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        intent: Optional[str],
        llm: "LLMProvider",
        recent_messages: Optional[list[dict[str, str]]] = None,
        scope: Optional[str] = None,
    ) -> None:
        """Decide what (if anything) to store from a turn, and maybe summarize.

        Designed to be scheduled with ``asyncio.create_task`` — it awaits its own
        work and swallows every error, so it never disturbs the request that
        spawned it.
        """
        if not self._enabled:
            return
        scope = scope or self._scope
        try:
            extracted = await self._updater.extract(user_text, assistant_text, intent, llm)
            for item in extracted:
                await self._remember_one(item, scope)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory update failed (%s)", exc)

        # Periodically distil the running conversation into one compact summary.
        try:
            if recent_messages and len(recent_messages) >= self._summary_threshold:
                if len(recent_messages) % self._summary_threshold == 0:
                    await self._summarize(recent_messages, llm, scope)
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation summarization failed (%s)", exc)

    async def _remember_one(self, item: ExtractedMemory, scope: str) -> None:
        content = item.content.strip()
        if not content:
            return
        embedding = (await self._embeddings.embed([content]))[0]

        existing = self._storage.get_by_key(scope, item.key) if item.key else None
        if existing is None:
            existing = self._find_duplicate(scope, item.type, embedding)

        now = datetime.utcnow()
        if existing is not None:
            existing.content = content
            existing.importance = max(existing.importance, item.importance)
            existing.embedding = embedding
            existing.key = existing.key or item.key
            existing.updated_at = now
            self._storage.update(existing)
            log.info("memory: updated (%s) %r", existing.type.value, content[:60])
        else:
            record = MemoryRecord.create(
                item.type, content, importance=item.importance, key=item.key, scope=scope
            )
            record.embedding = embedding
            self._storage.add(record)
            log.info("memory: stored (%s) %r", record.type.value, content[:60])

    def _find_duplicate(
        self, scope: str, type: MemoryType, embedding: list[float]
    ) -> Optional[MemoryRecord]:
        """Find an existing same-type memory near-identical to ``embedding``."""
        for rec in self._storage.list(scope, types=[type]):
            if rec.embedding and cosine(embedding, rec.embedding) >= _DEDUP_THRESHOLD:
                return rec
        return None

    async def _summarize(
        self, messages: list[dict[str, str]], llm: "LLMProvider", scope: str
    ) -> None:
        summary = await self._summarizer.summarize(messages, llm)
        if not summary:
            return
        # One evolving summary per scope — upsert by a stable key.
        await self._remember_one(
            ExtractedMemory(
                type=MemoryType.CONVERSATION_SUMMARY,
                content=summary,
                importance=0.6,
                key=f"conversation_summary:{scope}",
                action="update",
            ),
            scope,
        )
        log.info("memory: conversation summary updated for scope=%s", scope)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Small status dict for /health (never raises)."""
        try:
            count = self._storage.count(self._scope)
        except Exception:  # noqa: BLE001
            count = -1
        return {
            "enabled": self._enabled,
            "embeddings": getattr(self._embeddings, "name", "unknown"),
            "scope": self._scope,
            "records": count,
        }

    def close(self) -> None:
        """Release the storage backend's resources (never raises)."""
        closer = getattr(self._storage, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Factory — assemble a manager from settings
# ---------------------------------------------------------------------------

def build_memory_manager() -> MemoryManager:
    """Construct the MemoryManager from ``app.config.settings``.

    Reads only configuration; the LLM is supplied per-call by the pipeline, so
    the manager stays independent of which provider is active. Always returns a
    usable manager — if memory is disabled in config, the manager is a safe
    no-op that returns empty context and stores nothing.
    """
    from ..config import settings

    embeddings = build_embedding_provider(
        getattr(settings, "embedding_provider", "local"),
        gemini_api_key=getattr(settings, "gemini_api_key", None),
        openai_api_key=getattr(settings, "openai_api_key", None),
        local_dim=getattr(settings, "memory_embedding_dim", 256),
    )

    # Open the persistent store defensively. A corrupt or unreadable DB file
    # must NOT take down the whole backend at startup — memory is a feature, not
    # a prerequisite. On failure, fall back to an ephemeral in-memory store and
    # disable memory for this run; the operator can move/remove the bad file to
    # restore persistence. The corrupt file is left untouched for inspection.
    enabled = getattr(settings, "memory_enabled", True)
    try:
        storage: StorageBackend = SQLiteStorage(settings.memory_db_path)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "memory store at %s could not be opened (%s); memory DISABLED for this run. "
            "Move or remove that file to restore persistent memory.",
            settings.memory_db_path, exc,
        )
        storage = SQLiteStorage(":memory:")
        enabled = False

    retriever = Retriever(
        weight_semantic=getattr(settings, "memory_weight_semantic", 0.6),
        weight_recency=getattr(settings, "memory_weight_recency", 0.2),
        weight_importance=getattr(settings, "memory_weight_importance", 0.2),
        recency_half_life_days=getattr(settings, "memory_recency_half_life_days", 14.0),
    )
    manager = MemoryManager(
        storage=storage,
        embeddings=embeddings,
        retriever=retriever,
        updater=MemoryUpdater(),
        summarizer=Summarizer(),
        scope=(settings.user_name or "global"),
        enabled=enabled,
        max_injected=getattr(settings, "memory_max_injected", 6),
        min_score=getattr(settings, "memory_min_score", 0.15),
        summary_threshold=getattr(settings, "memory_summary_threshold", 20),
    )
    log.info(
        "MemoryManager ready (enabled=%s, embeddings=%s, scope=%s)",
        manager.enabled, getattr(embeddings, "name", "?"), settings.user_name or "global",
    )
    return manager
