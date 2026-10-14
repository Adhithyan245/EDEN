"""Updater — the memory decision stage: decide what a turn is worth remembering.

Not every exchange deserves memory. After a turn, this asks the active LLM to
extract only durable, worth-keeping facts (a name, a preference, a goal, a
project, a decision) and to classify each as store / update / ignore. A turn
with nothing durable yields nothing — the common case.

The decision is provider-agnostic: it uses only ``LLMProvider.stream_reply``.
With a non-reasoning provider (MockLLM/ScriptedLLM) the extraction JSON simply
won't contain memories, so the heuristic result is "remember nothing" — safe,
never junk. The manager applies dedup on top of these decisions, so an item is
never duplicated even if the model says "store" for something already known.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from . import _llm
from .models import ExtractedMemory, MemoryType

if TYPE_CHECKING:
    from ..providers.base import LLMProvider

log = logging.getLogger("eden.memory.updater")

_VALID_TYPES = ", ".join(t.value for t in MemoryType)

_SYSTEM = f"""\
You maintain the long-term memory of an assistant named EDEN. Given the latest
exchange, decide what — if anything — is worth remembering about the user for
future conversations.

Remember ONLY durable, reusable facts: the user's name or role, stable
preferences, long-term goals, projects they are working on, and important
decisions. Do NOT remember greetings, small talk, one-off questions, the
assistant's own answers, or anything that will not matter next time.

Respond with ONE valid JSON object and nothing else:

{{
  "memories": [
    {{
      "type": "<one of: {_VALID_TYPES}>",
      "content": "<a concise third-person note, e.g. 'Prefers dark mode UIs'>",
      "importance": <0.0-1.0>,
      "key": "<optional stable id for updates, e.g. 'profile:name'; omit if none>",
      "action": "store" | "update" | "ignore"
    }}
  ]
}}

If nothing is worth remembering, return {{"memories": []}}. Prefer an empty list
over storing something trivial. Use "key" for singular facts that should
overwrite rather than accumulate (the user's name, their current main project).
"""


class MemoryUpdater:
    """Runs the extract/decide stage over a single conversation turn."""

    async def extract(
        self,
        user_text: str,
        assistant_text: str,
        intent: Optional[str],
        llm: "LLMProvider",
    ) -> list[ExtractedMemory]:
        """Return candidate memories for this turn (possibly empty).

        Never raises: any LLM/parse failure yields an empty list so the caller's
        turn is never affected by a memory hiccup.
        """
        if not _llm.has_llm(llm):
            return []

        user_prompt = (
            f"User said: {user_text}\n"
            f"EDEN replied: {assistant_text}\n"
            f"(detected intent: {intent or 'unknown'})\n\n"
            "Extract memories as specified."
        )
        raw = await _llm.complete(llm, user=user_prompt, system=_SYSTEM, cap=3000)
        if not raw:
            return []

        try:
            from ..utils import extract_json
            data = extract_json(raw)
        except Exception:  # noqa: BLE001
            return []

        items = data.get("memories") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []

        extracted: list[ExtractedMemory] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            action = str(item.get("action") or "store").strip().lower()
            if not content or action == "ignore":
                continue
            try:
                importance = float(item.get("importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5
            key = item.get("key")
            key = str(key).strip() if key else None
            extracted.append(
                ExtractedMemory(
                    type=MemoryType.coerce(item.get("type")),
                    content=content,
                    importance=max(0.0, min(1.0, importance)),
                    key=key,
                    action=action if action in ("store", "update") else "store",
                )
            )

        if extracted:
            log.info("memory extraction: %d item(s) proposed", len(extracted))
        return extracted
