"""GeminiLLM retry / fallback behaviour, against a fake client (no network)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.providers import llm_gemini
from app.providers.llm_gemini import GeminiLLM, _is_retryable


class APIError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"{code} error")
        self.code = code


class _Chunk:
    def __init__(self, text: str) -> None:
        self.text = text


def _llm(script: dict[str, list]) -> tuple[GeminiLLM, list[str]]:
    """Build a GeminiLLM whose client follows ``script``: model -> outcomes.

    Each outcome is an exception (raised before streaming), a list of chunk
    texts, or ("partial", texts, exc) to fail mid-stream.
    """
    calls: list[str] = []

    async def generate_content_stream(*, model, contents, config):
        calls.append(model)
        outcome = script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        async def gen():
            if outcome == "stall":
                await asyncio.sleep(10)
                yield _Chunk("too late")
                return
            if isinstance(outcome, tuple) and outcome[0] == "slow":
                await asyncio.sleep(0.05)
                for t in outcome[1]:
                    yield _Chunk(t)
                return
            if isinstance(outcome, tuple):
                _, texts, exc = outcome
                for t in texts:
                    yield _Chunk(t)
                raise exc
            for t in outcome:
                yield _Chunk(t)

        return gen()

    llm = GeminiLLM.__new__(GeminiLLM)
    llm._client = SimpleNamespace(aio=SimpleNamespace(
        models=SimpleNamespace(generate_content_stream=generate_content_stream)))
    return llm, calls


async def _collect(llm: GeminiLLM, model: str) -> str:
    out = []
    async for t in llm.stream_reply([{"role": "user", "content": "hi"}], "sys", model=model):
        out.append(t)
    return "".join(out)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(llm_gemini, "_RETRY_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(llm_gemini.settings, "model_fallback", "fallback-model")
    monkeypatch.setattr(llm_gemini, "_BREAKER", llm_gemini._Breaker())


def test_success_first_try():
    llm, calls = _llm({"primary": [["he", "llo"]]})
    assert asyncio.run(_collect(llm, "primary")) == "hello"
    assert calls == ["primary"]


def test_retries_503_on_same_model():
    llm, calls = _llm({"primary": [APIError(503), ["ok"]]})
    assert asyncio.run(_collect(llm, "primary")) == "ok"
    assert calls == ["primary", "primary"]


def test_switches_to_fallback_after_primary_exhausted():
    llm, calls = _llm({"primary": [APIError(503), APIError(429)], "fallback-model": [["ok"]]})
    assert asyncio.run(_collect(llm, "primary")) == "ok"
    assert calls == ["primary", "primary", "fallback-model"]


def test_raises_after_all_attempts_fail():
    llm, calls = _llm({"primary": [APIError(503)] * 2, "fallback-model": [APIError(503)] * 2})
    with pytest.raises(APIError):
        asyncio.run(_collect(llm, "primary"))
    assert len(calls) == 4


def test_non_retryable_error_raises_immediately():
    llm, calls = _llm({"primary": [APIError(400)]})
    with pytest.raises(APIError):
        asyncio.run(_collect(llm, "primary"))
    assert calls == ["primary"]


def test_no_retry_after_partial_output():
    llm, calls = _llm({"primary": [("partial", ["half"], APIError(503))]})
    with pytest.raises(APIError):
        asyncio.run(_collect(llm, "primary"))
    assert calls == ["primary"]


def test_is_retryable_classification():
    assert _is_retryable(APIError(503)) and _is_retryable(APIError(429))
    assert _is_retryable(APIError(404))  # missing model -> try the fallback
    assert not _is_retryable(APIError(400)) and not _is_retryable(APIError(403))
    assert not _is_retryable(ValueError("bad"))


def test_breaker_routes_to_fallback_while_primary_cools_down():
    llm, calls = _llm({"primary": [APIError(503), APIError(503)],
                       "fallback-model": [["one"], ["two"]]})
    assert asyncio.run(_collect(llm, "primary")) == "one"
    assert asyncio.run(_collect(llm, "primary")) == "two"
    # Second request skipped the cooling-down primary entirely.
    assert calls == ["primary", "primary", "fallback-model", "fallback-model"]


def test_breaker_resets_after_cooldown(monkeypatch):
    monkeypatch.setattr(llm_gemini, "_COOLDOWN_SECONDS", -1.0)
    llm, calls = _llm({"primary": [APIError(503), APIError(503), ["back"]],
                       "fallback-model": [["one"]]})
    asyncio.run(_collect(llm, "primary"))
    assert asyncio.run(_collect(llm, "primary")) == "back"
    assert calls[-1] == "primary"


def test_cooling_primary_is_still_last_resort():
    llm, calls = _llm({"primary": [APIError(503), APIError(503), ["late"]],
                       "fallback-model": [["one"], APIError(503), APIError(503)]})
    asyncio.run(_collect(llm, "primary"))
    assert asyncio.run(_collect(llm, "primary")) == "late"
    assert calls[-3:] == ["fallback-model", "fallback-model", "primary"]


def test_stalled_model_misses_deadline_and_fallback_answers(monkeypatch):
    monkeypatch.setattr(llm_gemini, "_FIRST_CHUNK_TIMEOUT", 0.05)
    llm, calls = _llm({"primary": ["stall", "stall"], "fallback-model": [["quick"]]})
    assert asyncio.run(_collect(llm, "primary")) == "quick"
    assert calls == ["primary", "primary", "fallback-model"]


def test_final_attempt_has_no_deadline(monkeypatch):
    monkeypatch.setattr(llm_gemini, "_FIRST_CHUNK_TIMEOUT", 0.01)
    monkeypatch.setattr(llm_gemini.settings, "model_fallback", None)
    llm, calls = _llm({"primary": [APIError(503), ("slow", ["ok"])]})
    # second (final) attempt streams normally even though it's not instant
    assert asyncio.run(_collect(llm, "primary")) == "ok"
