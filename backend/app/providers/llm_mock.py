"""Mock LLM provider — lets EDEN run end-to-end with zero credentials.

Returns a JSON payload compatible with the personality layer's emotion
extraction so the full pipeline (emotion event → re-stream → TTS) works in
dev without any API keys.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

from ..agents.intent import IntentType
from .base import Message


class MockLLM:
    name = "mock"

    async def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
        intent: Optional[IntentType] = None,
    ) -> AsyncIterator[str]:
        user = messages[-1]["content"] if messages else ""
        payload = json.dumps({
            "emotion": "idle",
            "response": (
                f"I am running on the mock reasoning layer — no live model is connected. "
                f"You said: \"{user[:80]}\". "
                f"Add GEMINI_API_KEY to backend/.env to activate the real model."
            ),
        })
        yield payload
