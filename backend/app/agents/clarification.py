"""Clarification — decide whether to ask ONE question before building.

An experienced engineer does not start typing the moment a request arrives; they
first make sure they understand the problem. But they also do not interrogate —
they ask only when the answer would genuinely change what gets built.

This module makes that single judgement call. It errs strongly toward NOT asking:
a specific request ("modern calculator", "stopwatch", "weather dashboard") starts
immediately; only a genuinely ambiguous one whose answer changes the architecture
earns a question — and never more than one.

The actual wording EDEN speaks is produced by the narrator in EDEN's voice; this
module only decides *whether* and supplies the semantic question.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from ..providers.base import LLMProvider
from ..utils import extract_json

log = logging.getLogger("eden.agents.clarification")


@dataclass
class ClarificationDecision:
    needs:    bool
    question: Optional[str] = None
    reason:   str           = ""


_SYSTEM = """\
You are an experienced software engineer deciding whether you need ONE clarifying
question before building a small single-page web app. Respond with ONE valid JSON
object only — no markdown, no commentary.

{
  "needs_clarification": <true|false>,
  "question": <a single short question, or null>,
  "reason": "<short>"
}

Ask ONLY when the answer would materially change the architecture or core design,
exactly as a thoughtful engineer would. Never ask obvious or unnecessary
questions. Never ask more than one. When in doubt, do NOT ask.

Ask (the KIND of thing worth one question):
  - attendance system → is it for a school, a university, or a company?
  - portfolio site → is the goal professional or creative?
  - task manager → one person or a team?
  - expense tracker → local storage or user accounts?

Do NOT ask — start immediately (needs_clarification=false):
  - "a modern calculator", "a weather dashboard", "a stopwatch", "a todo list",
    "a notes app", or any request already specific enough to begin.

Keep the question to one sentence, plain and natural. Do not stack options with
"and". One decision only.
"""


class ClarificationManager:
    """Decides whether a build request needs one clarifying question."""

    async def assess(
        self,
        request: str,
        features: list[str],
        llm: LLMProvider,
    ) -> ClarificationDecision:
        hint = f"\nAlready specified: {', '.join(features)}" if features else ""
        try:
            raw_parts: list[str] = []
            async for chunk in llm.stream_reply(
                [{"role": "user", "content": f"Build request: {request}{hint}"}],
                _SYSTEM,
            ):
                raw_parts.append(chunk)
                if len("".join(raw_parts)) > 800:
                    break
            data = extract_json("".join(raw_parts).strip())
        except Exception as exc:  # noqa: BLE001
            # Fail open: if we cannot decide, do not block the build with a question.
            log.warning("clarification assess failed (%s); proceeding without asking", exc)
            return ClarificationDecision(needs=False, reason="assess failed; not asking")

        needs = bool(data.get("needs_clarification"))
        question = data.get("question")
        question = str(question).strip() if question else None
        if not question:
            needs = False
        return ClarificationDecision(
            needs=needs,
            question=question,
            reason=str(data.get("reason", "")),
        )


# Module-level singleton
clarification_manager = ClarificationManager()
