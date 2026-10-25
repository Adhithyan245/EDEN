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

import logging
import time
from typing import AsyncIterator, Optional

from google import genai
from google.genai import types

from ..config import settings

log = logging.getLogger("eden.tts.gemini")

SAMPLE_RATE = 24000

# A failing model (quota, overload) is skipped for this long.
_COOLDOWN_SECONDS = 120.0


class GeminiTTS:
    name = "gemini"
    engine = "server_stream"
    sample_rate = SAMPLE_RATE

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

        Falls through to the next model only before any audio was yielded, so
        a listener never hears a line restart.
        """
        prompt = f"{settings.tts_style}: {text}" if settings.tts_style else text
        now = time.monotonic()
        models = [m for m in self._models if now >= self._down_until.get(m, 0.0)] or self._models
        last_exc: Optional[Exception] = None
        for model in models:
            yielded = False
            try:
                async for chunk in await self._client.aio.models.generate_content_stream(
                    model=model, contents=prompt, config=self._config,
                ):
                    for part in _parts(chunk):
                        data = part.inline_data.data if part.inline_data else None
                        if data:
                            yielded = True
                            yield data
                self._down_until.pop(model, None)
                if yielded:
                    return
                last_exc = RuntimeError(f"{model} returned no audio")
            except Exception as exc:  # noqa: BLE001
                if yielded:
                    raise
                last_exc = exc
            self._down_until[model] = time.monotonic() + _COOLDOWN_SECONDS
            log.warning("gemini tts: %s failed (%s)", model, str(last_exc)[:160])
        raise last_exc or RuntimeError("no TTS model available")


def _parts(chunk) -> list:
    if not chunk.candidates or not chunk.candidates[0].content:
        return []
    return chunk.candidates[0].content.parts or []
