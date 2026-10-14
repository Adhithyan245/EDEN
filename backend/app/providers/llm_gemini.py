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

import logging
from typing import AsyncIterator, Optional

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
        return {"max_output_tokens": 4096, "temperature": 0.3}

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

        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            log.error("Gemini API error (%s): %s", type(exc).__name__, exc)
            raise