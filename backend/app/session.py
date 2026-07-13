"""Per-connection session state (conversation history)."""

from __future__ import annotations


class Session:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})
