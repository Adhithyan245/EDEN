"""Retrieval — rank candidate memories for the current moment.

Given a query embedding and the candidate records for a scope, produce the
top-k most relevant, blending three signals with configurable weights:

  semantic   — cosine similarity between the query and the memory (what it's
               about). Falls back to token overlap when either side has no
               embedding, so ranking still works if embeddings are unavailable.
  recency    — exponential decay on how long ago the memory was last updated,
               so fresh context outranks stale context of equal relevance.
  importance — the stored importance of the memory, so profile facts and key
               decisions get a standing boost over incidental chatter.

Scoring is pure and stateless — it takes candidates in and returns ranked
results out — so it's trivial to unit-test and to re-tune against real logs.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from .models import MemoryRecord, RetrievedMemory


def _tokens(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def cosine(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is missing/degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def jaccard(a: str, b: str) -> float:
    """Token-set overlap in [0, 1] — the semantic fallback when embeddings are absent."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


class Retriever:
    """Weighted-score ranker over candidate memories.

    Weights need not sum to 1 — they are normalized internally — so callers can
    express relative emphasis freely from config.
    """

    def __init__(
        self,
        *,
        weight_semantic: float = 0.6,
        weight_recency: float = 0.2,
        weight_importance: float = 0.2,
        recency_half_life_days: float = 14.0,
    ) -> None:
        total = weight_semantic + weight_recency + weight_importance
        total = total if total > 0 else 1.0
        self.w_sem = weight_semantic / total
        self.w_rec = weight_recency / total
        self.w_imp = weight_importance / total
        self.half_life_days = max(0.1, recency_half_life_days)

    def _recency(self, updated_at: datetime, now: datetime) -> float:
        age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
        # 0.5 ** (age / half_life): 1.0 when fresh, 0.5 at one half-life, →0 as it ages.
        return 0.5 ** (age_days / self.half_life_days)

    def _semantic(
        self,
        query_embedding: Optional[list[float]],
        query_text: str,
        record: MemoryRecord,
    ) -> float:
        if query_embedding and record.embedding:
            return max(0.0, cosine(query_embedding, record.embedding))
        # Fallback: token overlap between the raw query and the memory content.
        return jaccard(query_text, record.content)

    def rank(
        self,
        query_embedding: Optional[list[float]],
        query_text: str,
        candidates: list[MemoryRecord],
        *,
        now: Optional[datetime] = None,
        limit: int = 6,
        min_score: float = 0.15,
    ) -> list[RetrievedMemory]:
        """Return up to ``limit`` candidates scoring at least ``min_score``, best first."""
        now = now or datetime.utcnow()
        scored: list[RetrievedMemory] = []
        for rec in candidates:
            sem = self._semantic(query_embedding, query_text, rec)
            rec_score = self._recency(rec.updated_at, now)
            imp = rec.importance
            blended = self.w_sem * sem + self.w_rec * rec_score + self.w_imp * imp
            scored.append(
                RetrievedMemory(
                    record=rec,
                    score=blended,
                    semantic_score=sem,
                    recency_score=rec_score,
                    importance_score=imp,
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return [r for r in scored if r.score >= min_score][:limit]
