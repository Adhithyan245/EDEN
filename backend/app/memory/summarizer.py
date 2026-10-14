"""Summarizer — compact a long conversation into a short, durable summary.

EDEN does not keep every message forever. When a conversation grows past a
threshold, its running content is distilled into a single compact
``conversation_summary`` memory that survives across sessions. This keeps
long-term memory small and retrievable without storing raw transcripts.

The summary is produced by whichever LLM provider is active; if that call
fails or returns nothing (e.g. MockLLM), a deterministic heuristic fallback
builds a plain digest so summarization never blocks or errors.

Note on scope: this produces a *memory artifact* only. It does not trim the
live conversation window the pipeline sends to the model — that is left intact
so conversational behavior is unchanged (see manager docstring, extension
points).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import _llm

if TYPE_CHECKING:
    from ..providers.base import LLMProvider

log = logging.getLogger("eden.memory.summarizer")

_SYSTEM = """\
You compress a conversation into a durable memory note for an assistant named EDEN.
Return ONE short paragraph (2-4 sentences) capturing only what is worth
remembering later: who the person is, what they are working on, decisions made,
and stated preferences. Omit greetings, small talk, and anything transient.
Write it as neutral notes in third person ("The user is building..."), not as
dialogue. Plain text only — no JSON, no markdown, no bullet points.
"""


class Summarizer:
    """Turns recent conversation turns into a compact summary string."""

    async def summarize(self, messages: list[dict[str, str]], llm: "LLMProvider") -> str:
        """Return a compact summary of ``messages`` (role/content dicts).

        Uses the LLM when available; falls back to a heuristic digest otherwise.
        Returns "" only if there is genuinely nothing to summarize.
        """
        transcript = self._render(messages)
        if not transcript.strip():
            return ""

        if _llm.has_llm(llm):
            summary = await _llm.complete(
                llm,
                user=f"Conversation so far:\n\n{transcript}\n\nWrite the memory note.",
                system=_SYSTEM,
                cap=2000,
            )
            summary = _strip_json_ish(summary)
            if summary:
                return summary

        return self._heuristic(messages)

    @staticmethod
    def _render(messages: list[dict[str, str]]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            speaker = "User" if role == "user" else "EDEN"
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _heuristic(messages: list[dict[str, str]]) -> str:
        """Dependency-free fallback: the most recent user turns, truncated."""
        user_turns = [
            (m.get("content") or "").strip()
            for m in messages
            if m.get("role") == "user" and (m.get("content") or "").strip()
        ]
        if not user_turns:
            return ""
        recent = user_turns[-5:]
        digest = " | ".join(t[:120] for t in recent)
        return f"Recent conversation topics: {digest}"


def _strip_json_ish(text: str) -> str:
    """If the provider wrapped prose in a JSON envelope, pull the text back out.

    MockLLM/ScriptedLLM return ``{"emotion":..,"response":..}``; a real model
    following the summary prompt returns plain text. Handle both so the summary
    is never a raw JSON blob.
    """
    t = text.strip()
    if t.startswith("{"):
        try:
            from ..utils import extract_json
            data = extract_json(t)
            return str(data.get("response") or data.get("summary") or "").strip()
        except Exception:  # noqa: BLE001
            return ""
    return t
