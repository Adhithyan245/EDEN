"""GeminiTTS model fallback and cooldown, against a fake client (no network)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.providers import tts_gemini
from app.providers.tts_gemini import GeminiTTS


def _chunk(data: bytes):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=data))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def _tts(script):
    calls = []

    async def generate_content_stream(*, model, contents, config):
        calls.append((model, contents))
        outcome = script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        async def gen():
            for d in outcome:
                yield _chunk(d)
        return gen()

    tts = GeminiTTS.__new__(GeminiTTS)
    tts._client = SimpleNamespace(aio=SimpleNamespace(
        models=SimpleNamespace(generate_content_stream=generate_content_stream)))
    tts._models = ["primary", "backup"]
    tts._down_until = {}
    tts._config = None
    return tts, calls


async def _collect(tts, text="hi"):
    return b"".join([c async for c in tts.stream(text)])


def test_streams_audio_with_style_prefix(monkeypatch):
    monkeypatch.setattr(tts_gemini.settings, "tts_style", "Say warmly")
    tts, calls = _tts({"primary": [[b"ab", b"cd"]]})
    assert asyncio.run(_collect(tts, "hello")) == b"abcd"
    assert calls == [("primary", "Say warmly: hello")]


def test_falls_back_and_cools_down_failing_model():
    tts, calls = _tts({"primary": [RuntimeError("429")], "backup": [[b"x"], [b"y"]]})
    assert asyncio.run(_collect(tts)) == b"x"
    assert asyncio.run(_collect(tts)) == b"y"
    assert [m for m, _ in calls] == ["primary", "backup", "backup"]


def test_empty_audio_counts_as_failure():
    tts, calls = _tts({"primary": [[]], "backup": [[b"z"]]})
    assert asyncio.run(_collect(tts)) == b"z"


def test_raises_when_every_model_fails():
    tts, _ = _tts({"primary": [RuntimeError("a")], "backup": [RuntimeError("b")]})
    with pytest.raises(RuntimeError):
        asyncio.run(_collect(tts))
