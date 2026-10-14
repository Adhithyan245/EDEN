"""Embedding tests: local determinism/normalization, similarity signal, factory fallback."""

from __future__ import annotations

import asyncio
import math

from app.memory.embeddings import (
    LocalHashEmbedding,
    build_embedding_provider,
)
from app.memory.retrieval import cosine


def _embed(provider, texts):
    return asyncio.run(provider.embed(texts))


def test_local_embedding_is_deterministic_across_instances():
    a = _embed(LocalHashEmbedding(), ["the quick brown fox"])[0]
    b = _embed(LocalHashEmbedding(), ["the quick brown fox"])[0]
    assert a == b  # stable md5 hashing, not process-randomized hash()


def test_local_embedding_is_l2_normalized():
    v = _embed(LocalHashEmbedding(), ["some words here"])[0]
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-9


def test_local_embedding_empty_text_is_zero_vector():
    v = _embed(LocalHashEmbedding(dim=32), [""])[0]
    assert len(v) == 32
    assert all(x == 0.0 for x in v)


def test_local_embedding_respects_dim():
    v = _embed(LocalHashEmbedding(dim=64), ["hello"])[0]
    assert len(v) == 64


def test_local_embedding_similarity_signal():
    prov = LocalHashEmbedding()
    q, near, far = _embed(
        prov,
        ["my favorite color is blue", "favorite color blue", "database migration schema"],
    )
    assert cosine(q, near) > cosine(q, far)


def test_factory_defaults_to_local():
    assert build_embedding_provider("local").name == "local-hash"


def test_factory_gemini_without_key_falls_back_to_local():
    assert build_embedding_provider("gemini", gemini_api_key=None).name == "local-hash"


def test_factory_openai_without_key_falls_back_to_local():
    assert build_embedding_provider("openai", openai_api_key=None).name == "local-hash"


def test_factory_unknown_kind_falls_back_to_local():
    assert build_embedding_provider("banana").name == "local-hash"
