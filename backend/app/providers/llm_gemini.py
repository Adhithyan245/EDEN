"""Gemini-backed LLM provider (Google AI API).

Used in LIVE/SAFE modes when GEMINI_API_KEY is available. Streams the reply
for low latency.

Model IDs verified by live probe (client.models.list() + generateContent call) on 2026-07-14:
  gemini-3.1-flash-lite — 0.66 s TTFT; only sub-second model available on the free
                          API tier; used for both voice turns and builder agent.
  gemini-3.5-flash      — thinking model; 10-20 s TTFT; unsuitable for voice streaming.
  gemini-2.5-flash/pro  — blocked for new API key users (404 / quota exceeded).
  Pro models            — quota-limited on the free tier; override EDEN_MODEL_BUILDER
                          with gemini-2.5-pro or gemini-3.1-pro-preview on a paid plan.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import httpx
from google import genai
from google.genai import types

from ..agents.intent import IntentType
from ..config import settings
from .base import Message

log = logging.getLogger("eden.llm.gemini")


def _generation_config(intent: Optional[IntentType]) -> dict:
    """Return Gemini generation parameters tuned for the detected intent.

    INFORMATION_QUERY gets the most headroom — detailed knowledge responses
    need space to breathe. BUILD gets deterministic low-temperature output.
    CONVERSATION gets a warmer, slightly more creative setting. Everything
    else falls back to a balanced default.
    """
    if intent == IntentType.INFORMATION_QUERY:
        # Depth over brevity: allow long, accurate, well-structured answers.
        return {"max_output_tokens": 8192, "temperature": 0.5}

    if intent == IntentType.BUILD:
        # Deterministic: complete App.jsx + styles without creative drift.
        # Whole source files escaped inside JSON are token-dense; 4096 tokens
        # (~8k chars) truncated larger apps mid-string (eden-bench-v1, B03).
        return {"max_output_tokens": 16384, "temperature": 0.3}

    if intent == IntentType.CONVERSATION:
        # Natural, warm conversational rhythm — short by EDEN's own choice.
        return {"max_output_tokens": 2048, "temperature": 0.7}

    # Default covers EDIT, EXPLAIN, DEMONSTRATE, DEBUG, and unknown intents.
    return {"max_output_tokens": 4096, "temperature": 0.6}


class GeminiLLM:
    name = "gemini"

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
        intent: Optional[IntentType] = None,
    ) -> AsyncIterator[str]:
        model = model or settings.model_voice

        gen_params = _generation_config(intent)
        log.info(
            "gemini generation: intent=%s model=%s max_tokens=%s temperature=%s",
            intent.value if intent else "none",
            model,
            gen_params["max_output_tokens"],
            gen_params["temperature"],
        )

        # Map messages to Gemini Content objects (role: "user" | "model")
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=gen_params["max_output_tokens"],
            temperature=gen_params["temperature"],
            # Enforce valid JSON output so the personality layer's emotion
            # extraction never receives malformed or markdown-wrapped responses.
            response_mime_type="application/json",
        )

        # Transient failures (503 overload, 429 rate limit, network blips) are
        # common on the free tier. Retry them, then switch to the fallback model
        # — but only before the first chunk is yielded, so a caller never sees
        # a reply restart halfway through.
        attempts = _attempt_plan(model, settings.model_fallback)
        for i, (attempt_model, delay) in enumerate(attempts):
            if delay:
                await asyncio.sleep(delay)
            yielded = False
            last = i == len(attempts) - 1
            try:
                # An overloaded model sometimes answers without erroring, just
                # 20 s late. Unless this is the final option, give it a deadline
                # to start streaming and move on to the next one if it misses.
                chunks = _first_chunk_deadline(
                    self._client.aio.models.generate_content_stream(
                        model=attempt_model,
                        contents=contents,
                        config=config,
                    ),
                    None if last else _FIRST_CHUNK_TIMEOUT,
                )
                async for chunk in chunks:
                    if chunk.text:
                        yielded = True
                        yield chunk.text
                _BREAKER.succeeded(attempt_model)
                if attempt_model != model:
                    log.info("gemini: served by fallback model %s", attempt_model)
                return
            except Exception as exc:
                if _is_retryable(exc):
                    _BREAKER.failed(attempt_model)
                if yielded or last or not _is_retryable(exc):
                    log.error("Gemini API error (%s): %s", type(exc).__name__, exc)
                    raise
                log.warning(
                    "gemini: %s on %s (attempt %d/%d) — retrying",
                    _status(exc) or type(exc).__name__, attempt_model, i + 1, len(attempts),
                )


# Seconds a non-final attempt may take to produce its first chunk. Healthy
# models stream within ~1 s; this only catches a stalled, overloaded one.
_FIRST_CHUNK_TIMEOUT = 8.0


async def _first_chunk_deadline(request, timeout: Optional[float]):
    """Iterate a streaming request, failing if the first chunk takes too long."""
    if timeout is None:
        async for chunk in await request:
            yield chunk
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    stream = await asyncio.wait_for(request, timeout=timeout)
    it = stream.__aiter__()
    try:
        first = await asyncio.wait_for(it.__anext__(), timeout=max(0.1, deadline - loop.time()))
    except StopAsyncIteration:
        return
    except asyncio.TimeoutError:
        aclose = getattr(it, "aclose", None)
        if aclose:
            try:
                await aclose()
            except Exception:  # noqa: BLE001
                pass
        raise
    yield first
    async for chunk in it:
        yield chunk


# Primary model is tried twice, then the fallback twice. Delays are seconds
# before each attempt.
_RETRY_DELAYS = (0.0, 1.5)

# After a model fails with a retryable error, skip straight to the fallback for
# this long instead of waiting on the failing model every request. 503s from an
# overloaded model can take many seconds each to come back.
_COOLDOWN_SECONDS = 120.0


class _Breaker:
    def __init__(self) -> None:
        self._down_until: dict[str, float] = {}

    def failed(self, model: str) -> None:
        self._down_until[model] = time.monotonic() + _COOLDOWN_SECONDS

    def succeeded(self, model: str) -> None:
        self._down_until.pop(model, None)

    def is_down(self, model: str) -> bool:
        return time.monotonic() < self._down_until.get(model, 0.0)


_BREAKER = _Breaker()


def _attempt_plan(primary: str, fallback: Optional[str]) -> list[tuple[str, float]]:
    if not fallback or fallback == primary:
        return [(primary, d) for d in _RETRY_DELAYS]
    if _BREAKER.is_down(primary) and not _BREAKER.is_down(fallback):
        # Primary is cooling down: fallback first, primary once as a last resort.
        return [(fallback, d) for d in _RETRY_DELAYS] + [(primary, _RETRY_DELAYS[-1])]
    return [(primary, d) for d in _RETRY_DELAYS] + [(fallback, d) for d in _RETRY_DELAYS]


def _status(exc: Exception) -> Optional[int]:
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _is_retryable(exc: Exception) -> bool:
    """Overload, rate limit, server error, missing model, or a network failure."""
    code = _status(exc)
    if code is not None:
        return code in (404, 408, 429) or code >= 500
    return isinstance(exc, (httpx.TransportError, asyncio.TimeoutError, ConnectionError))