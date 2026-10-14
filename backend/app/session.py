"""Per-connection session state (conversation history + audience scope + pending question)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Scope = Literal["private", "public"]


@dataclass
class PendingClarification:
    """A clarifying question EDEN asked and is waiting on an answer for.

    Holds the original build request so the next message can be treated as the
    answer and the build resumed without asking the user to repeat themselves.
    """
    original_request: str
    question:         str
    features:         list[str] = field(default_factory=list)


class Session:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        # Whether EDEN is currently addressing one person or a room.
        # Sticky: flips to "public" on a wake / room address and stays there.
        self.audience_scope: Scope = "private"
        # A build clarification awaiting the user's answer, if any.
        self.pending_clarification: Optional[PendingClarification] = None

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})
