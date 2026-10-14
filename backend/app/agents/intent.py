"""Intent detection — classifies user input before routing.

Two-phase approach:
  Phase A: keyword pre-filter (fast, no LLM call).
           If no action-oriented keywords are present, returns CONVERSATION immediately.
  Phase B: LLM classification (only when Phase A suggests a non-conversational intent).
           Uses a focused system prompt separate from EDEN's personality.

Falls back to CONVERSATION on any LLM or parsing failure so the pipeline
is never blocked by a detection error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..providers.base import LLMProvider
from ..utils import extract_json

log = logging.getLogger("eden.agents.intent")


# ---------------------------------------------------------------------------
# Intent vocabulary
# ---------------------------------------------------------------------------

class IntentType(str, Enum):
    CONVERSATION      = "conversation"       # Normal EDEN dialogue — route to conversation pipeline
    BUILD             = "build"              # User wants to create a new application or tool
    EDIT              = "edit"               # User wants to modify the active, running project
    EXPLAIN           = "explain"            # User wants a concept or piece of code explained
    DEMONSTRATE       = "demonstrate"        # User wants something shown or walked through
    DEBUG             = "debug"              # User wants to fix or diagnose a problem
    INFORMATION_QUERY = "information_query"  # User wants knowledge, research, trends, or analysis


@dataclass
class IntentResult:
    """Structured output of the intent detector."""

    intent:     IntentType
    confidence: float                        # 0.0 – 1.0
    raw_text:   str
    app_type:   Optional[str] = None         # Free-form inferred label for BUILD, e.g. "attendance"
    app_name:   Optional[str] = None         # Human-readable name, e.g. "Attendance Tracker"
    features:   list[str]     = field(default_factory=list)
    reasoning:  str           = ""
    edit_op:    str           = "change"     # For EDIT: "change" | "undo" | "redo"


# ---------------------------------------------------------------------------
# Keyword sets for Phase A pre-filter
# ---------------------------------------------------------------------------
# The pre-filter only decides whether to spend an LLM call — it does not decide
# the intent. Any build verb is enough to escalate to classification, so novel
# app types ("attendance system", "expense tracker") are never missed just
# because their noun isn't in a hand-written list.

_BUILD_VERBS    = frozenset({"build", "create", "make", "generate", "write", "code", "develop"})
# Edit verbs escalate to classification whenever there is an active project;
# "make"/"add"/"change" overlap with build, so the classifier (with active-project
# context) makes the final build-vs-edit call.
_EDIT_VERBS     = frozenset({
    "make", "change", "update", "modify", "fix", "improve", "remove", "delete",
    "replace", "add", "refactor", "redesign", "adjust", "tweak", "move", "rename",
    "set", "turn", "swap", "resize", "recolor", "recolour", "restyle",
})
# Version-history cues (only meaningful when a project is running).
_UNDO_CUES      = ("undo", "revert", "roll back", "rollback", "go back",
                   "older version", "previous version", "last version",
                   "the old version", "liked the old", "liked the older",
                   "bring back the old", "back to the old", "take it back")
_REDO_CUES      = ("redo", "re-apply", "reapply", "re-do", "apply it again",
                   "bring that back", "put that back")
_EXPLAIN_KW     = frozenset({"explain", "what is", "how does", "describe", "tell me about", "what are"})
_DEMONSTRATE_KW = frozenset({"demonstrate", "show me", "show how", "demo", "example", "walk me through"})
_DEBUG_KW       = frozenset({"debug", "fix", "broken", "error", "not working", "issue", "problem", "bug", "fails"})

# Information query keywords — escalate to LLM classification for deeper
# reasoning about whether this is a knowledge/research request vs casual chat.
# Keywords alone do not decide the intent; the LLM makes the final call.
_INFO_KW        = frozenset({
    "latest", "recent", "trends", "trend", "news", "developments", "updates",
    "overview", "research", "paper", "papers", "compare", "comparison",
    "difference between", "guide", "tutorial", "how does", "why does",
    "what happened", "where is", "heading", "future of",
})


# ---------------------------------------------------------------------------
# LLM classification prompt (Phase B)
# ---------------------------------------------------------------------------

_CLASSIFICATION_SYSTEM = """\
You are a precise intent classifier for an AI coding agent.
Respond ONLY with a single valid JSON object — no markdown, no commentary, no extra text.

Schema:
{
  "intent": "conversation" | "build" | "edit" | "explain" | "demonstrate" | "debug" | "information_query",
  "confidence": <float 0.0–1.0>,
  "app_type": <string or null>,
  "app_name": <string or null>,
  "features": [<string>, ...],
  "edit_op": "change" | "undo" | "redo",
  "reasoning": "<one sentence>"
}

Intent definitions:
  build             — user wants to create a NEW application, website, or software tool
  edit              — user wants to MODIFY the application that is already running
  explain           — user wants a concept, technology, or code segment explained
  demonstrate       — user wants to see something shown or walked through step-by-step
  debug             — user wants to fix or diagnose a problem in existing code
  information_query — user wants knowledge, analysis, research, or factual information
                      about the world, technology trends, recent events, or any topic
                      that requires a substantive informational answer
  conversation      — casual chat, greetings, personal conversation, jokes, opinions,
                      and short social interactions that do not require deep knowledge

information_query vs conversation — this is the key distinction for non-build messages:
  - "How are you?" / "Good morning" / "Tell me a joke" → conversation
  - "What are the latest AI trends?" / "Explain transformer architecture" /
    "Compare GPT and Claude" / "What happened recently in robotics?" /
    "Where is AI heading in the next five years?" → information_query
  - Use information_query whenever the user expects a substantive, knowledge-based
    answer — even if the phrasing sounds casual or does not contain obvious keywords.
  - Use conversation only for exchanges where a brief social reply is the correct
    and complete response.

information_query examples:
  "What are the latest trends in AI?"           → information_query
  "Explain retrieval augmented generation."     → information_query
  "What happened recently in robotics?"         → information_query
  "Compare GPT-5 and Claude."                   → information_query
  "Why does gradient descent work?"             → information_query
  "Where is AI heading in the next five years?" → information_query
  "Give me an overview of diffusion models."    → information_query

Build vs edit — this is the key distinction for construction requests:
  - If the message names a new app to create ("build me a calculator", "make a
    todo app"), it is "build".
  - If there is an ACTIVE PROJECT and the message asks to change it ("make the
    buttons blue", "add dark mode", "move the header", "make it prettier",
    "improve the UI", "add animations"), it is "edit".
  - "make"/"add"/"change" alone do not decide it — the presence of an active
    project and whether a new app is named do.
  - If the message asks to modify something but there is NO active project, it is
    not "edit"; treat it as "conversation" (there is nothing to modify).
  - "Explain how AI chatbots work" is information_query, not build, even though
    it mentions AI chatbots.

For "build" intent:
  Infer app_type as a short one or two word label (e.g. "calculator", "todo",
  "attendance", "quiz", "notes", "timer", "weather dashboard", "expense
  tracker"). No fixed list — infer it. Leave app_type null only if you truly
  cannot tell. Set app_name to a short human-readable title. Set features to any
  specific capabilities mentioned.

For "edit" intent:
  Leave app_type / app_name null (the active project already has them). Put the
  concrete change(s) requested into features when clear.
  Set edit_op: "undo" if they want to revert / go back to an earlier version
  ("undo that", "I liked the older version"), "redo" to re-apply an undone
  change, otherwise "change". For non-edit intents leave edit_op as "change".

Set confidence to reflect how certain you are.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def detect_intent(
    text: str,
    llm: LLMProvider,
    active_project: Optional[str] = None,
) -> IntentResult:
    """Classify the user message and return a structured IntentResult.

    Uses Phase A keyword pre-filter to short-circuit obvious conversational
    messages without an LLM call. When ``active_project`` (a one-line summary) is
    provided, edit verbs escalate to classification and the classifier is told a
    project is running so it can distinguish "edit" from "build". Falls back to
    CONVERSATION on any error.
    """
    text_l = text.lower()

    has_build       = any(v in text_l for v in _BUILD_VERBS)
    has_edit        = any(v in text_l for v in _EDIT_VERBS)
    has_version_cue = any(c in text_l for c in _UNDO_CUES) or any(c in text_l for c in _REDO_CUES)
    has_explain     = any(kw in text_l for kw in _EXPLAIN_KW)
    has_demonstrate = any(kw in text_l for kw in _DEMONSTRATE_KW)
    has_debug       = any(kw in text_l for kw in _DEBUG_KW)
    has_info        = any(kw in text_l for kw in _INFO_KW)

    # Edit verbs and version cues only matter when there is something to edit.
    edit_relevant = (has_edit or has_version_cue) and active_project is not None
    op = _detect_edit_op(text_l)  # "change" | "undo" | "redo"

    if not (has_build or edit_relevant or has_explain or has_demonstrate or has_debug or has_info):
        return IntentResult(
            intent=IntentType.CONVERSATION,
            confidence=0.95,
            raw_text=text,
            reasoning="no action-oriented keywords detected — fast-path conversation",
        )

    # Phase B: LLM classification. Give the model the active-project context so it
    # can resolve build-vs-edit correctly.
    user_content = text
    if active_project:
        user_content = (
            f"[ACTIVE PROJECT: {active_project}]\n"
            f"A project is already running. If this message asks to change it, the "
            f"intent is 'edit'.\n\nMessage: {text}"
        )
    try:
        raw_parts: list[str] = []
        async for chunk in llm.stream_reply(
            [{"role": "user", "content": user_content}],
            _CLASSIFICATION_SYSTEM,
        ):
            raw_parts.append(chunk)
            if len("".join(raw_parts)) > 1200:
                break

        raw = "".join(raw_parts).strip()
        data = extract_json(raw)

        intent_raw = str(data.get("intent", "conversation")).lower()
        try:
            intent = IntentType(intent_raw)
        except ValueError:
            intent = IntentType.CONVERSATION

        confidence = float(data.get("confidence", 0.7))

        app_type = data.get("app_type")
        if isinstance(app_type, str):
            app_type = app_type.lower().strip() or None

        app_name = data.get("app_name")
        if app_name:
            app_name = str(app_name).strip() or None

        features = [str(f) for f in (data.get("features") or []) if f]

        # Resolve the edit operation. Keyword cues (undo/redo) are highly reliable,
        # so they win; otherwise trust the classifier, else default to "change".
        edit_op = op if op != "change" else str(data.get("edit_op") or "change").lower()
        if edit_op not in ("change", "undo", "redo"):
            edit_op = "change"

        result = IntentResult(
            intent=intent,
            confidence=confidence,
            raw_text=text,
            app_type=app_type,
            app_name=app_name,
            features=features,
            reasoning=str(data.get("reasoning", "")),
            edit_op=edit_op,
        )
        log.info(
            "intent=%s confidence=%.2f app_type=%s edit_op=%s",
            result.intent.value, result.confidence, result.app_type, result.edit_op,
        )
        return result

    except Exception as exc:  # noqa: BLE001
        log.warning("intent LLM classification failed (%s); using keyword heuristic", exc)
        # Keyword heuristic fallback.
        # With an active project, a modification verb means edit; a build verb that
        # names a new app means build. Prefer edit when a project is running and the
        # message reads as a change rather than a fresh "build a ..." request.
        if edit_relevant and not (has_build and _names_new_app(text_l)):
            return IntentResult(
                intent=IntentType.EDIT,
                confidence=0.6,
                raw_text=text,
                reasoning="edit verb with active project; LLM fallback",
                edit_op=op,
            )
        if has_build:
            return IntentResult(
                intent=IntentType.BUILD,
                confidence=0.6,
                raw_text=text,
                reasoning="keyword match; LLM fallback",
            )
        if has_debug:
            return IntentResult(
                intent=IntentType.DEBUG,
                confidence=0.6,
                raw_text=text,
                reasoning="debug keyword match; LLM fallback",
            )
        if has_explain:
            return IntentResult(
                intent=IntentType.EXPLAIN,
                confidence=0.6,
                raw_text=text,
                reasoning="explain keyword match; LLM fallback",
            )
        if has_info:
            return IntentResult(
                intent=IntentType.INFORMATION_QUERY,
                confidence=0.6,
                raw_text=text,
                reasoning="information keyword match; LLM fallback",
            )
        return IntentResult(
            intent=IntentType.CONVERSATION,
            confidence=0.6,
            raw_text=text,
            reasoning="LLM failed; defaulting to conversation",
        )


# Heuristic used only in the LLM-failure fallback: does the message read like it
# names a NEW app to build (e.g. "build me a calculator app") rather than a
# change to the running one?
_NEW_APP_HINTS = frozenset({"app", "application", "website", "site", "tool", "new"})


def _names_new_app(text_l: str) -> bool:
    return any(h in text_l for h in _NEW_APP_HINTS)


def _detect_edit_op(text_l: str) -> str:
    """Classify an edit message as a version op: 'undo', 'redo', or 'change'."""
    if any(c in text_l for c in _REDO_CUES):
        return "redo"
    if any(c in text_l for c in _UNDO_CUES):
        return "undo"
    return "change"