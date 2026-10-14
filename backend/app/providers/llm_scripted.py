"""Scripted LLM provider for PRESENTATION mode — zero external calls.

Matches the user's input against curated demo responses by keyword overlap and
streams the best match. This guarantees the signature lecture moments always
work, even with no network at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator, Optional

from ..agents.intent import IntentType
from .base import Message

_CACHE = Path(__file__).resolve().parent.parent / "cache" / "demo_responses.json"


class ScriptedLLM:
    name = "scripted"

    def __init__(self) -> None:
        data = json.loads(_CACHE.read_text(encoding="utf-8")) if _CACHE.exists() else {}
        self._responses: list[dict] = data.get("responses", [])
        self._default: str = data.get(
            "default", "I don't have a scripted answer for that one, but I'm still here."
        )

    def _match(self, user: str) -> str:
        user_l = user.lower()
        best_score = 0
        best_response = self._default
        for entry in self._responses:
            keywords = [k.lower() for k in entry.get("keywords", [])]
            score = sum(1 for k in keywords if k in user_l)
            if score > best_score:
                best_score = score
                best_response = entry.get("response", self._default)
        return best_response

    async def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
        intent: Optional[IntentType] = None,
    ) -> AsyncIterator[str]:
        import json
        user = messages[-1]["content"] if messages else ""
        reply = self._match(user)
        yield json.dumps({"emotion": "confident", "response": reply})
