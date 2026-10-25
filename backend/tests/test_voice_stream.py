"""Streamed speech: framing, ordering, and fallback to browser speech."""

from __future__ import annotations

import asyncio
import base64

from app import voice


class _WS:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


class _StreamTTS:
    name = "fake"
    engine = "server_stream"
    sample_rate = 24000

    def __init__(self, chunks=(), fail_after=None, delay=0.0) -> None:
        self.chunks, self.fail_after, self.delay = list(chunks), fail_after, delay

    async def synthesize(self, text):
        return None

    async def stream(self, text):
        for i, c in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("quota")
            await asyncio.sleep(self.delay)
            yield c
        if self.fail_after is not None and self.fail_after >= len(self.chunks):
            raise RuntimeError("quota")


def _run(ws, tts, *texts):
    async def go():
        for t in texts:
            await voice.speak(ws, tts, t)
        await voice.drain()
    asyncio.run(go())


def _pcm(ws, sid):
    return b"".join(base64.b64decode(e["pcm_b64"]) for e in ws.events
                    if e["type"] == "speech_chunk" and e["id"] == sid)


def test_stream_frames_all_audio_in_order():
    chunks = [bytes([i % 256]) * 3001 for i in range(9)]  # odd sizes on purpose
    ws = _WS()
    _run(ws, _StreamTTS(chunks), "hello")
    types = [e["type"] for e in ws.events]
    assert types[0] == "speech_stream_start" and types[-1] == "speech_stream_end"
    sid = ws.events[0]["id"]
    seqs = [e["seq"] for e in ws.events if e["type"] == "speech_chunk"]
    assert seqs == list(range(len(seqs)))
    sent = _pcm(ws, sid)
    assert sent == b"".join(chunks)[: len(sent)]
    assert len(b"".join(chunks)) - len(sent) <= 1   # only a dangling odd byte dropped
    assert all(len(base64.b64decode(e["pcm_b64"])) % 2 == 0
               for e in ws.events if e["type"] == "speech_chunk")
    assert ws.events[-1]["ok"] is True


def test_first_frame_is_small_for_fast_start():
    ws = _WS()
    _run(ws, _StreamTTS([b"\0\0" * 2400] + [b"\0\0" * 2400] * 5), "hi")
    first = next(e for e in ws.events if e["type"] == "speech_chunk")
    assert len(base64.b64decode(first["pcm_b64"])) <= 6000


def test_failure_before_audio_falls_back_to_browser():
    ws = _WS()
    _run(ws, _StreamTTS([b"\0\0" * 100], fail_after=0), "fallback please")
    assert [e["type"] for e in ws.events] == ["speak"]
    assert ws.events[0]["text"] == "fallback please"


def test_failure_mid_stream_ends_the_stream_not_restarts():
    ws = _WS()
    _run(ws, _StreamTTS([b"\0\0" * 3000, b"\0\0" * 3000], fail_after=2), "cut")
    types = [e["type"] for e in ws.events]
    assert "speak" not in types
    assert types[-1] == "speech_stream_end" and ws.events[-1]["ok"] is False


def test_lines_stay_in_order_on_one_connection():
    ws = _WS()
    _run(ws, _StreamTTS([b"\0\0" * 3000] * 3, delay=0.01), "one", "two", "three")
    starts = [e["text"] for e in ws.events if e["type"] == "speech_stream_start"]
    assert starts == ["one", "two", "three"]
    # No interleaving: each line's end precedes the next line's start.
    order = [(e["type"], e.get("id")) for e in ws.events
             if e["type"] in ("speech_stream_start", "speech_stream_end")]
    assert [t for t, _ in order] == ["speech_stream_start", "speech_stream_end"] * 3


def test_speak_returns_before_streaming_finishes():
    ws = _WS()

    async def go():
        await voice.speak(ws, _StreamTTS([b"\0\0" * 3000] * 5, delay=0.05), "slow line")
        sent_when_returned = len(ws.events)
        await voice.drain()
        return sent_when_returned

    assert asyncio.run(go()) == 0  # the pipeline isn't held up by speech
    assert ws.events[-1]["type"] == "speech_stream_end"


def test_browser_engine_unchanged():
    class _Browser:
        engine = "browser"
    ws = _WS()
    asyncio.run(voice.speak(ws, _Browser(), "plain"))
    assert ws.events == [{"type": "speak", "text": "plain"}]
