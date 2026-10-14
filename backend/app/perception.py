"""Perception — reading the context of an incoming message before the LLM sees it.

Two things are detected here, both cheaply and deterministically (no LLM call):

  1. Wake phrases  — the cinematic lecture opening ("good morning everyone").
  2. Audience scope — is EDEN speaking privately to one person, or publicly to a room?

Both follow the same design philosophy already blessed in the project: for
high-stakes contextual signals, explicit detection + a context marker is more
reliable than asking the model to infer it probabilistically. The marker is
injected into the message sent to the LLM; the personality prompt explains how
to behave. The original user text is never modified in session history.

Audience scope is *sticky*: once a lecture goes public (a wake, or an explicit
address to the room), EDEN stays in public mode for the rest of the session.
That mirrors reality — you do not drift back to a private tone mid-presentation.
"""

from __future__ import annotations

from typing import Literal

Scope = Literal["private", "public"]


# ---------------------------------------------------------------------------
# Wake detection
# ---------------------------------------------------------------------------

_WAKE_PATTERNS: frozenset[str] = frozenset({
    "good morning everyone",
    "good morning, everyone",
    "good afternoon everyone",
    "good afternoon, everyone",
    "good evening everyone",
    "good evening, everyone",
    "hello everyone",
    "hello, everyone",
    "hi everyone",
    "hi, everyone",
})


def is_wake_phrase(text: str) -> bool:
    """True if the message is an audience-directed greeting that opens the demo."""
    return text.lower().strip().rstrip("!.,?") in _WAKE_PATTERNS


# ---------------------------------------------------------------------------
# Audience scope detection
# ---------------------------------------------------------------------------

# Cues that indicate EDEN is now addressing a room, not one person.
_PUBLIC_CUES: tuple[str, ...] = (
    "everyone",
    "everybody",
    "the audience",
    "the room",
    "the class",
    "the students",
    "you all",
    "y'all",
    "all of you",
    "to the room",
    "to everyone",
    "introduce yourself to",
    "say hi to",
    "greet everyone",
    "greet the",
)


def _looks_public(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in _PUBLIC_CUES)


def resolve_scope(text: str, current: Scope, *, is_wake: bool = False) -> Scope:
    """Return the audience scope for this turn, honoring stickiness.

    Once ``current`` is "public" it stays public. A wake phrase, or any explicit
    address to the room, flips a private session to public.
    """
    if current == "public":
        return "public"
    if is_wake or _looks_public(text):
        return "public"
    return "private"
