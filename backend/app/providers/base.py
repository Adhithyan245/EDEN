"""Provider interfaces. Concrete implementations live alongside this file.

The rest of the app depends only on these Protocols, never on a specific
vendor — this is what makes Gemini/ElevenLabs swappable and lets EDEN fall
back to mock/scripted/browser providers with zero credentials.

Canonical LLM interface: every ``LLMProvider`` implementation (Gemini, Mock,
Scripted, or any future addition) must expose exactly the ``stream_reply``
signature declared below — same parameters, same return type, same async/
streaming contract. Callers (``main.py``, ``narrator.py``, the agent
planners) call ``stream_reply`` uniformly and never check which provider is
active; that uniformity is only real if every implementation matches this
Protocol exactly, so changing this signature means updating every provider
in the same change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Literal, Optional, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    # Deferred: agents.intent imports LLMProvider from this module, so importing
    # IntentType at runtime here would be circular. Only needed for type-checking.
    from ..agents.intent import IntentType


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
        intent: Optional["IntentType"] = None,
    ) -> AsyncIterator[str]:
        """Yield the reply as text deltas.

        ``model`` optionally overrides the provider's default model.
        ``intent`` carries the detected conversational intent so a provider
        may tune generation (token budget, temperature) per request type; a
        provider that has no use for it must still accept and ignore it.

        A provider that cannot truly stream a live response (e.g. a single
        cached or templated reply) must still return an async generator that
        yields at least once, so every caller can uniformly do
        ``async for delta in provider.stream_reply(...)`` with no special-casing
        for which provider is active.
        """
        ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    # server_audio:  synthesize() returns a complete audio file (ElevenLabs MP3)
    # server_stream: also has ``stream(text)`` yielding PCM16 chunks at
    #                ``sample_rate`` (Gemini); see voice.py
    # browser:       the frontend speaks with SpeechSynthesis
    engine: Literal["server_audio", "server_stream", "browser"]

    async def synthesize(self, text: str) -> Optional[bytes]:
        """Return audio bytes for ``server_audio`` engines, or ``None`` to
        delegate speech to the browser (``browser`` engine)."""
        ...
