"""Shared TTS delivery helper.

Extracted from main.py so both the conversational pipeline and the agent
orchestrator can speak through the same code path without duplication.

Streaming voices (Gemini) send ``speech_stream_start`` → ``speech_chunk``… →
``speech_stream_end`` and the frontend plays each chunk as it lands. If the
stream can't start (quota, outage), the provider's ``fallback`` voice (e.g.
ElevenLabs) speaks the line, and browser speech is the last resort. Streaming
runs in the background so a narration never holds up a build, and one lock per
connection keeps lines in order: a line starts only after the previous one has
finished sending (the frontend queues playback the same way).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
import weakref

from fastapi import WebSocket

from . import events
from .providers.base import TTSProvider

log = logging.getLogger("eden.voice")

# ~0.25 s of 24 kHz PCM16 per frame; the first frame goes out as soon as it has
# ~0.1 s so playback starts with minimal delay.
_FRAME_BYTES = 12000
_FIRST_FRAME_BYTES = 4800

_locks: "weakref.WeakKeyDictionary[WebSocket, asyncio.Lock]" = weakref.WeakKeyDictionary()
_pending: set[asyncio.Task] = set()


async def speak(websocket: WebSocket, tts: TTSProvider, text: str) -> None:
    """Voice ``text`` via the selected TTS provider, falling back to the browser.

    Emits ``speech_audio`` (ElevenLabs path), a speech stream (Gemini path), or
    ``speak`` (browser path). Silently falls back to browser voice on any TTS
    failure so the pipeline is never blocked by a single failed synthesis call.
    """
    if not text.strip():
        return
    engine = getattr(tts, "engine", "browser")
    if engine == "browser":
        await websocket.send_json(events.speak(text))
        return
    if engine == "server_stream":
        task = asyncio.create_task(_stream_in_order(websocket, tts, text))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
        return
    try:
        audio = await tts.synthesize(text)
        if audio:
            b64 = base64.b64encode(audio).decode("ascii")
            await websocket.send_json(events.speech_audio(b64))
        else:
            await websocket.send_json(events.speak(text))
    except Exception as exc:  # noqa: BLE001
        log.warning("TTS failed (%s); falling back to browser voice", exc)
        await websocket.send_json(events.speak(text))


async def drain() -> None:
    """Wait for in-flight streamed speech (tests and benchmarks)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


async def _stream_in_order(websocket: WebSocket, tts: TTSProvider, text: str) -> None:
    lock = _locks.setdefault(websocket, asyncio.Lock())
    async with lock:
        try:
            await stream_speech(websocket, tts, text)
        except Exception as exc:  # noqa: BLE001 — a closed socket, most likely
            log.debug("speech stream aborted (%s)", exc)


async def stream_speech(websocket: WebSocket, tts: TTSProvider, text: str) -> None:
    """Send one line as a speech stream; browser speech if nothing came back."""
    sid = uuid.uuid4().hex[:12]
    started = False
    seq = 0
    buf = bytearray()

    async def flush() -> None:
        nonlocal seq
        # Keep frames sample-aligned (2 bytes per 16-bit sample).
        cut = len(buf) - (len(buf) % 2)
        if not cut:
            return
        await websocket.send_json(
            events.speech_chunk(sid, seq, base64.b64encode(bytes(buf[:cut])).decode("ascii"))
        )
        del buf[:cut]
        seq += 1

    try:
        async for pcm in tts.stream(text):
            if not started:
                await websocket.send_json(
                    events.speech_stream_start(sid, getattr(tts, "sample_rate", 24000), text)
                )
                started = True
            buf.extend(pcm)
            if len(buf) >= (_FIRST_FRAME_BYTES if seq == 0 else _FRAME_BYTES):
                await flush()
        await flush()
        if started:
            await websocket.send_json(events.speech_stream_end(sid, ok=True))
    except Exception as exc:  # noqa: BLE001
        log.warning("streamed TTS failed (%s)", exc)
        if started:
            await flush()
            await websocket.send_json(events.speech_stream_end(sid, ok=False))
            return
    if not started:
        await _fallback_voice(websocket, tts, text)


async def _fallback_voice(websocket: WebSocket, tts: TTSProvider, text: str) -> None:
    """The streaming voice couldn't speak: try its fallback, then the browser."""
    fallback = getattr(tts, "fallback", None)
    if fallback is not None:
        try:
            audio = await fallback.synthesize(text)
            if audio:
                b64 = base64.b64encode(audio).decode("ascii")
                await websocket.send_json(events.speech_audio(b64))
                return
        except Exception as exc:  # noqa: BLE001
            log.warning("fallback voice %s failed (%s)", getattr(fallback, "name", "?"), exc)
    await websocket.send_json(events.speak(text))
