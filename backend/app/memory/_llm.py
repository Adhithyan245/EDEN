"""Tiny internal helper: run a one-shot completion against any LLM provider.

The memory subsystem needs occasional LLM calls (deciding what to remember,
summarizing a long conversation) but must not care which provider is active.
It relies only on the canonical ``LLMProvider.stream_reply`` interface
(``app/providers/base.py``) — buffering the stream into a single string — so
Gemini, MockLLM, ScriptedLLM, or any future provider all work unchanged.

``intent`` is intentionally never passed: memory's internal calls are their own
kind of task, unrelated to the conversational intent taxonomy, and every
provider treats a missing ``intent`` as the neutral default.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid a runtime import cycle / coupling to the providers package
    from ..providers.base import LLMProvider

log = logging.getLogger("eden.memory.llm")


async def complete(llm: "LLMProvider", user: str, system: str, *, cap: int = 4000) -> str:
    """Return the provider's full reply to ``user`` under ``system`` as one string.

    ``cap`` bounds how many characters are buffered before the stream is cut —
    memory prompts are small, so this only guards against a runaway provider.
    Never raises: on any provider error it logs and returns an empty string,
    letting the caller fall back to its heuristic path.
    """
    parts: list[str] = []
    try:
        async for chunk in llm.stream_reply([{"role": "user", "content": user}], system):
            parts.append(chunk)
            if len("".join(parts)) > cap:
                break
    except Exception as exc:  # noqa: BLE001 — memory must never break the caller
        log.warning("memory LLM call failed (%s); caller will use its fallback", exc)
        return ""
    return "".join(parts).strip()


def has_llm(llm: Any) -> bool:
    """True if ``llm`` looks like a usable provider (has ``stream_reply``)."""
    return llm is not None and hasattr(llm, "stream_reply")
