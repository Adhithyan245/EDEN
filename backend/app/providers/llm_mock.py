"""Mock LLM provider — lets EDEN run end-to-end with zero credentials.

Used whenever no Claude access is configured (outside PRESENTATION mode).
Streams a plausible reply word-by-word so the full UI/voice loop works in dev.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from .base import Message


class MockLLM:
    name = "mock"

    async def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        user = messages[-1]["content"] if messages else ""
        reply = (
            f"This is EDEN's mock reasoning layer - no live model is connected yet. "
            f"You said: \"{user[:120]}\". Once an Anthropic API key is configured, "
            f"I'll answer for real."
        )
        for word in reply.split(" "):
            yield word + " "
            await asyncio.sleep(0.03)
