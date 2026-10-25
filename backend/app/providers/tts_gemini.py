"""Gemini streaming TTS — natural speech with ElevenLabs-class latency.

Gemini's speech models stream raw audio (16-bit PCM, 24 kHz, mono) while they
generate, faster than real time. Measured on 2026-10-25 with this project's
key: first audio after 0.7-1.0 s, about 13 s of speech generated in about 4 s.
The frontend plays chunks as they arrive, so EDEN starts talking after about a
second instead of waiting for the whole line.

The model takes a short spoken-style direction ahead of the text. It must stay
short and in the "Say ...:" form: longer instructions get read aloud.

Uses the same GEMINI_API_KEY as the LLM, so it adds no new credential or bill.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

from google import genai
from google.genai import types

from ..config import settings

log = logging.getLogger("eden.tts.gemini")

SAMPLE_RATE = 24000

# A failing or stalling model (quota, overload) is skipped for this long.
_COOLDOWN_SECONDS = 120

# If the first model hasn't produced audio by now, start the next in parallel.
# Healthy first audio is ~0.7 s; a stalled request was measured at ~8 s.
_HEDGE_SECONDS = 1.5

# Give up on a line (caller falls back to browser speech) if no model has
# produced audio by now, or if a started stream goes silent this long.
_FIRST_AUDIO_TIMEOUT = 10.0
_STALL_TIMEOUT = 10.0


class GeminiTTS:
    name = "gemini"
    engine = "server_stream"
    sample_rate = SAMPLE_RATE
    # Optional complete-file voice used when no Gemini model can speak
    # (set by the factory, e.g. ElevenLabs). Browser speech is the last resort.
    fallback = None

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._models = [m for m in (settings.tts_model, settings.tts_model_fallback) if m]
        self._down_until: dict[str, float] = {}
        self._config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.tts_voice)
                )
            ),
        )

    async def synthesize(self, text: str) -> Optional[bytes]:
        """Non-streaming callers get browser speech; EDEN uses ``stream``."""
        return None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield PCM16 chunks for ``text``. Raises if no model produced audio.

        Hedged: if the first model hasn't produced audio within
        ``_HEDGE_SECONDS``, the next model starts in parallel and whichever
        speaks first is used (the other is cancelled). A model that errors or
        loses the race is skipped for ``_COOLDOWN_SECONDS``. Once audio starts
        there is no switching, so a listener never hears a line restart.
        """
        prompt = f"{settings.tts_style}: {text}" if settings.tts_style else text
        now = time.monotonic()
        queue_models = [m for m in self._models if now >= self._down_until.get(m, 0.0)]
        if not queue_models:
            # Every model is cooling down (typically the daily free quota):
            # fail fast so the fallback voice speaks without an extra delay.
            raise RuntimeError("all Gemini voice models are cooling down")
        racers: list[tuple[str, asyncio.Queue, asyncio.Task]] = []

        def launch() -> bool:
            if not queue_models:
                return False
            model = queue_models.pop(0)
            q: asyncio.Queue = asyncio.Queue()
            racers.append((model, q, asyncio.create_task(self._pump(model, prompt, q))))
            return True

        launch()
        winner = None
        first = b""
        last_exc: Optional[BaseException] = None
        give_up = time.monotonic() + _FIRST_AUDIO_TIMEOUT
        try:
            while winner is None:
                if not racers and not launch():
                    raise last_exc or RuntimeError("no TTS model available")
                remaining = give_up - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no audio within {_FIRST_AUDIO_TIMEOUT:.0f}s")
                gets = {asyncio.ensure_future(q.get()): (m, q, t) for m, q, t in racers}
                hedge = _HEDGE_SECONDS if (len(racers) == 1 and queue_models) else None
                wait = min(hedge, remaining) if hedge is not None else remaining
                done, pending = await asyncio.wait(gets, timeout=wait,
                                                   return_when=asyncio.FIRST_COMPLETED)
                for g in pending:
                    g.cancel()
                if not done and not (hedge is not None and wait == hedge):
                    continue  # overall deadline reached; the check above raises
                if not done:
                    log.info("gemini tts: %s slow to start; hedging with %s",
                             racers[0][0], queue_models[0])
                    launch()
                    continue
                for g in done:
                    model, q, task = gets[g]
                    item = g.result()
                    if isinstance(item, (bytes, bytearray)) and winner is None:
                        winner, first = (model, q, task), bytes(item)
                    elif not isinstance(item, (bytes, bytearray)):
                        # An error, or the stream ended without any audio.
                        last_exc = (item if isinstance(item, BaseException)
                                    else RuntimeError(f"{model} returned no audio"))
                        self._mark_down(model, last_exc)
                        racers.remove((model, q, task))
            model, q, task = winner
            for other_model, _, other_task in racers:
                if other_task is not task:
                    other_task.cancel()
                    self._mark_down(other_model, RuntimeError("slower than the hedge"))
            self._down_until.pop(model, None)
            yield first
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=_STALL_TIMEOUT)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"{model} stalled mid-line") from None
                if item is _END:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            # Stop every model stream still running (the winner's too, if the
            # listener went away mid-line).
            for _, _, t in racers:
                t.cancel()

    async def _pump(self, model: str, prompt: str, q: asyncio.Queue) -> None:
        """Run one model's stream into ``q``: bytes…, then _END or an exception."""
        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model, contents=prompt, config=self._config,
            ):
                for part in _parts(chunk):
                    data = part.inline_data.data if part.inline_data else None
                    if data:
                        await q.put(data)
            await q.put(_END)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await q.put(exc)

    def _mark_down(self, model: str, exc: BaseException) -> None:
        self._down_until[model] = time.monotonic() + _COOLDOWN_SECONDS
        log.warning("gemini tts: %s skipped for %ds (%s)", model, _COOLDOWN_SECONDS,
                    str(exc)[:160])


_END = object()


def _parts(chunk) -> list:
    if not chunk.candidates or not chunk.candidates[0].content:
        return []
    return chunk.candidates[0].content.parts or []
