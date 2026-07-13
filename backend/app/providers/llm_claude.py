"""Claude-backed LLM provider (Anthropic API).

Used in LIVE/SAFE modes when credentials are available. Streams the reply for
low latency. Extended thinking is intentionally off for conversational turns
(the agent orchestrator will enable adaptive thinking in Day 4).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import anthropic

from ..config import settings
from .base import Message

log = logging.getLogger("eden.llm.claude")

# Models that support the extended-thinking API (and therefore accept the
# thinking={"type":"disabled"} parameter).  For other models we just omit it.
_THINKING_CAPABLE = {
    "claude-3-7-sonnet",
    "claude-sonnet-5",
    "claude-opus-4",
    "claude-opus-4-8",
    "claude-fable-5",
}


def _supports_thinking(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in _THINKING_CAPABLE)


class ClaudeLLM:
    name = "claude"

    def __init__(self) -> None:
        # Reads ANTHROPIC_API_KEY env var, or an active `claude`/`ant` login
        # profile, automatically.  Raises AuthenticationError at first API call
        # (not here) if neither is present — the factory's except clause catches
        # that and falls back to MockLLM.
        self._client = anthropic.AsyncAnthropic()

    async def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        model = model or settings.model_voice

        params: dict = dict(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        )
        # Explicitly disable extended thinking only for models that support the
        # parameter — omitting it is equivalent for other models.
        if _supports_thinking(model):
            params["thinking"] = {"type": "disabled"}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.AuthenticationError:
            log.error(
                "Anthropic authentication failed. "
                "Check ANTHROPIC_API_KEY in backend/.env, or set EDEN_ASSUME_ANTHROPIC=true "
                "if you are authenticated via the Claude CLI."
            )
            raise
        except anthropic.RateLimitError:
            log.warning("Anthropic rate limit hit — retrying is not implemented; reply will be empty.")
            raise
        except anthropic.APIConnectionError as exc:
            log.error("Cannot reach Anthropic API: %s", exc)
            raise
        except anthropic.APIStatusError as exc:
            log.error("Anthropic API error %s: %s", exc.status_code, exc.message)
            raise
