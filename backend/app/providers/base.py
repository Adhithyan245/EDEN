"""Provider interfaces. Concrete implementations live alongside this file.

The rest of the app depends only on these Protocols, never on a specific
vendor — this is what makes Claude/ElevenLabs swappable and lets EDEN fall
back to mock/browser providers with zero credentials.
"""

from __future__ import annotations

from typing import AsyncIterator, Literal, Optional, Protocol, TypedDict, runtime_checkable


class Message(TypedDict):
    role: str  # "user" | "assistant"
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def stream_reply(
        self,
        messages: list[Message],
        system: str,
        *,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Yield the reply as text deltas."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    engine: Literal["server_audio", "browser"]

    async def synthesize(self, text: str) -> Optional[bytes]:
        """Return audio bytes for ``server_audio`` engines, or ``None`` to
        delegate speech to the browser (``browser`` engine)."""
        ...
