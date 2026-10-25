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
            if outcome and outcome[0] == "delay":
                await asyncio.sleep(outcome[1])
                items = outcome[2:]
            else:
                items = outcome
            for d in items:
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


def test_hedge_uses_backup_when_primary_is_slow(monkeypatch):
    monkeypatch.setattr(tts_gemini, "_HEDGE_SECONDS", 0.05)
    tts, calls = _tts({"primary": [["delay", 1.0, b"late"]], "backup": [[b"fast", b"er"]]})
    assert asyncio.run(_collect(tts)) == b"faster"
    assert [m for m, _ in calls] == ["primary", "backup"]
    assert "primary" in tts._down_until  # slow model is skipped next time


def test_no_hedge_when_primary_is_quick(monkeypatch):
    monkeypatch.setattr(tts_gemini, "_HEDGE_SECONDS", 0.5)
    tts, calls = _tts({"primary": [[b"quick"]], "backup": [[b"unused"]]})
    assert asyncio.run(_collect(tts)) == b"quick"
    assert [m for m, _ in calls] == ["primary"]


def test_primary_wins_if_it_speaks_before_backup(monkeypatch):
    monkeypatch.setattr(tts_gemini, "_HEDGE_SECONDS", 0.05)
    tts, calls = _tts({"primary": [["delay", 0.1, b"p"]], "backup": [["delay", 1.0, b"b"]]})
    assert asyncio.run(_collect(tts)) == b"p"
    assert "backup" in tts._down_until


def test_error_mid_stream_raises_without_switching():
    tts, calls = _tts({"primary": [[b"a"]], "backup": [[b"b"]]})

    async def broken(model, prompt, q):
        await q.put(b"a")
        await q.put(RuntimeError("cut"))
    tts._pump = broken
    with pytest.raises(RuntimeError):
        asyncio.run(_collect(tts))


def test_gives_up_when_no_model_produces_audio(monkeypatch):
    monkeypatch.setattr(tts_gemini, "_HEDGE_SECONDS", 0.02)
    monkeypatch.setattr(tts_gemini, "_FIRST_AUDIO_TIMEOUT", 0.15)
    tts, _ = _tts({"primary": [["delay", 5, b"x"]], "backup": [["delay", 5, b"y"]]})
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(_collect(tts), 2))


def test_mid_line_stall_ends_the_stream(monkeypatch):
    monkeypatch.setattr(tts_gemini, "_STALL_TIMEOUT", 0.1)
    tts, _ = _tts({"primary": [[b"a"]], "backup": [[b"b"]]})

    async def stalls(model, prompt, q):
        await q.put(b"a")
        await asyncio.sleep(5)
    tts._pump = stalls
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(_collect(tts), 2))


def test_hedge_winner_keeps_streaming_after_the_loser_is_cancelled(monkeypatch):
    # Real streams trickle in over seconds; the winner must not be cancelled
    # along with the loser (regression: identity check cancelled both).
    monkeypatch.setattr(tts_gemini, "_HEDGE_SECONDS", 0.02)
    tts, _ = _tts({"primary": [[]], "backup": [[]]})

    async def pump(model, prompt, q):
        if model == "primary":
            await asyncio.sleep(5)
            return
        for piece in (b"one ", b"two ", b"three"):
            await q.put(piece)
            await asyncio.sleep(0.05)
        await q.put(tts_gemini._END)
    tts._pump = pump
    assert asyncio.run(asyncio.wait_for(_collect(tts), 2)) == b"one two three"
    assert "backup" not in tts._down_until and "primary" in tts._down_until


def test_fails_fast_when_every_model_is_cooling_down():
    tts, calls = _tts({"primary": [[b"x"]], "backup": [[b"y"]]})
    import time as _t
    tts._down_until = {"primary": _t.monotonic() + 60, "backup": _t.monotonic() + 60}
    with pytest.raises(RuntimeError, match="cooling down"):
        asyncio.run(_collect(tts))
    assert calls == []  # no wasted request while the quota is exhausted
