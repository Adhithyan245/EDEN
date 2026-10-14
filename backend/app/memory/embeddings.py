"""Embedding providers — turn text into vectors for semantic retrieval.

This mirrors the LLM/TTS provider pattern: callers depend only on the
``EmbeddingProvider`` interface and never on a specific vendor. The factory
picks one from config, and any failure degrades to the always-available local
provider so the memory subsystem — like the rest of EDEN — runs with zero
credentials and zero network.

Providers:
  LocalHashEmbedding  — default. Dependency-free, offline, deterministic. A
                        hashed bag-of-tokens vector: crude but a real, stable
                        similarity signal (shared vocabulary → higher cosine).
  GeminiEmbedding     — uses the google-genai client already in the project.
  OpenAIEmbedding     — uses the openai package if installed.

Determinism note: Python's built-in ``hash()`` of a string is randomized per
process, which would make stored vectors incomparable across restarts. The
local provider therefore hashes with md5, which is stable forever.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger("eden.memory.embeddings")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Canonical embedding interface. Every provider matches this exactly."""

    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized vector per input text (same order)."""
        ...


# ---------------------------------------------------------------------------
# Local, dependency-free default
# ---------------------------------------------------------------------------

class LocalHashEmbedding:
    """Offline hashed bag-of-tokens embedding. Always available.

    Tokenizes to lowercase alphanumerics, hashes each token to a bucket via a
    stable digest, accumulates term frequency, then L2-normalizes. Cosine
    similarity between two such vectors rises with shared vocabulary — enough
    to make "what's my name" retrieve a stored name preference, without any
    model download or API call. Designed to be swapped for a real embedding
    model later with no change to callers.
    """

    name = "local-hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @staticmethod
    def _bucket(token: str, dim: int) -> int:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "little") % dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN_RE.findall(text.lower()):
            vec[self._bucket(tok, self.dim)] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t or "") for t in texts]


# ---------------------------------------------------------------------------
# Gemini (google-genai — already a project dependency)
# ---------------------------------------------------------------------------

class GeminiEmbedding:
    """Embeddings via the google-genai client. Optional; needs GEMINI_API_KEY."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = "text-embedding-004", dim: int = 768) -> None:
        self._api_key = api_key
        self._model = model
        self.dim = dim
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            from google import genai  # lazy; only when this provider is actually used
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        loop = asyncio.get_event_loop()

        def _call() -> list[list[float]]:
            client = self._get_client()
            resp = client.models.embed_content(model=self._model, contents=texts)
            # google-genai returns an object with `.embeddings`, each having `.values`.
            out: list[list[float]] = []
            for emb in getattr(resp, "embeddings", []) or []:
                values = list(getattr(emb, "values", None) or emb)
                out.append(_l2(values))
            return out

        return await loop.run_in_executor(None, _call)


# ---------------------------------------------------------------------------
# OpenAI (optional; only if the openai package is installed)
# ---------------------------------------------------------------------------

class OpenAIEmbedding:
    """Embeddings via the OpenAI API. Optional; needs OPENAI_API_KEY + openai pkg."""

    name = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1536) -> None:
        self._api_key = api_key
        self._model = model
        self.dim = dim
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # lazy
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        loop = asyncio.get_event_loop()

        def _call() -> list[list[float]]:
            client = self._get_client()
            resp = client.embeddings.create(model=self._model, input=texts)
            return [_l2(list(item.embedding)) for item in resp.data]

        return await loop.run_in_executor(None, _call)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_embedding_provider(
    kind: str,
    *,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    local_dim: int = 256,
) -> EmbeddingProvider:
    """Return the configured embedding provider, degrading to local on any issue.

    ``kind`` is one of ``local`` | ``gemini`` | ``openai``. A requested remote
    provider with no key (or that fails to construct) silently falls back to the
    local provider — memory should never be disabled just because an optional
    embedding backend is unavailable.
    """
    kind = (kind or "local").strip().lower()

    if kind == "gemini" and gemini_api_key:
        try:
            log.info("embeddings -> GeminiEmbedding")
            return GeminiEmbedding(api_key=gemini_api_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("GeminiEmbedding init failed (%s); using local embeddings", exc)

    if kind == "openai" and openai_api_key:
        try:
            log.info("embeddings -> OpenAIEmbedding")
            return OpenAIEmbedding(api_key=openai_api_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenAIEmbedding init failed (%s); using local embeddings", exc)

    if kind not in ("local", "gemini", "openai"):
        log.warning("unknown embedding provider %r; using local embeddings", kind)

    log.info("embeddings -> LocalHashEmbedding (dim=%d)", local_dim)
    return LocalHashEmbedding(dim=local_dim)


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec
