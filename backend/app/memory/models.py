"""Memory data model — the shapes the whole subsystem agrees on.

Everything else in ``app/memory`` (storage, embeddings, retrieval, updating,
summarizing) is defined in terms of these types. Nothing here depends on a
storage backend, an embedding vendor, or an LLM provider, so the model stays
portable if any of those are swapped later.

A single ``MemoryRecord`` is one durable thing EDEN knows — a preference, a
fact, a goal, a project, a conversation summary. Records carry enough metadata
(type, importance, timestamps, access stats, an optional dedup ``key``, and an
optional embedding) for the retriever to rank them and the updater to decide
whether a new observation is novel, a duplicate, or an update to something
already known.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class MemoryType(str, Enum):
    """The category of a memory. Drives filtering, formatting, and weighting.

    Values are stable wire/DB strings — changing one requires a data migration.
    """

    USER_PROFILE         = "user_profile"          # who the person is (name, role, background)
    PREFERENCE           = "preference"            # how they like things done
    GOAL                 = "goal"                  # long-term aims
    CURRENT_PROJECT      = "current_project"       # what they are actively working on
    PROJECT_HISTORY      = "project_history"       # things built/worked on before
    CONVERSATION_SUMMARY = "conversation_summary"  # compacted history of a long conversation
    FACT                 = "fact"                  # a durable fact learned in conversation
    DECISION             = "decision"              # an important decision that was made
    ACTIVE_TASK          = "active_task"           # something in progress
    COMPLETED_TASK       = "completed_task"        # something finished

    @classmethod
    def coerce(cls, value: Any) -> "MemoryType":
        """Return a MemoryType for ``value``, defaulting to FACT on anything unknown.

        The updater's LLM extraction can return arbitrary strings; this keeps a
        bad label from ever crashing the store — it just files it as a FACT.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.FACT


def _now() -> datetime:
    return datetime.utcnow()


@dataclass
class MemoryRecord:
    """One durable unit of memory.

    ``key`` is an optional stable identity used for upserts — e.g. a profile
    field like ``"profile:name"`` or the evolving ``"conversation_summary"``.
    When two observations share a ``key`` (and scope) the newer one updates the
    older rather than creating a duplicate. Records without a key fall back to
    semantic near-duplicate detection in the updater.

    ``scope`` partitions memory (per user / per deployment). The default single
    user lives under one scope so memory persists across sessions.

    ``embedding`` is filled in by the manager before storage; it may be ``None``
    for records created before an embedding provider was available.
    """

    id:               str
    type:             MemoryType
    content:          str
    importance:       float               = 0.5   # 0..1 — how much this should weigh in retrieval
    key:              Optional[str]       = None
    scope:            str                 = "global"
    metadata:         dict[str, Any]      = field(default_factory=dict)
    embedding:        Optional[list[float]] = None
    created_at:       datetime            = field(default_factory=_now)
    updated_at:       datetime            = field(default_factory=_now)
    last_accessed_at: Optional[datetime]  = None
    access_count:     int                 = 0

    @classmethod
    def create(
        cls,
        type: MemoryType,
        content: str,
        *,
        importance: float = 0.5,
        key: Optional[str] = None,
        scope: str = "global",
        metadata: Optional[dict[str, Any]] = None,
    ) -> "MemoryRecord":
        """Build a fresh record with a new id and timestamps."""
        return cls(
            id         = str(uuid.uuid4()),
            type       = MemoryType.coerce(type),
            content    = content.strip(),
            importance = _clamp01(importance),
            key        = key,
            scope      = scope,
            metadata   = dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form (types as strings, datetimes as ISO). Storage/serialization."""
        return {
            "id":               self.id,
            "type":             self.type.value,
            "content":          self.content,
            "importance":       self.importance,
            "key":              self.key,
            "scope":            self.scope,
            "metadata":         self.metadata,
            "embedding":        self.embedding,
            "created_at":       self.created_at.isoformat(),
            "updated_at":       self.updated_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "access_count":     self.access_count,
        }


@dataclass
class RetrievedMemory:
    """A record plus the score that earned it a place in the prompt.

    The component scores are retained (not just the blended total) so retrieval
    decisions are debuggable and the weights can be tuned against real logs.
    """

    record:            MemoryRecord
    score:             float   # blended, 0..1
    semantic_score:    float   # similarity component, 0..1
    recency_score:     float   # freshness component, 0..1
    importance_score:  float   # stored importance, 0..1


@dataclass
class ExtractedMemory:
    """A candidate memory proposed by the updater's decision stage.

    ``action`` is the decision: ``store`` (new), ``update`` (revise existing),
    or ``ignore`` (drop). The manager applies dedup safety on top of this, so
    an ``action`` of ``store`` that turns out to duplicate an existing memory is
    still folded into an update rather than creating a second copy.
    """

    type:       MemoryType
    content:    str
    importance: float = 0.5
    key:        Optional[str] = None
    action:     str = "store"   # "store" | "update" | "ignore"


def _clamp01(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5
