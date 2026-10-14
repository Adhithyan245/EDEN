"""Agent router — decides whether a request enters the conversational pipeline
or the coding agent pipeline.

Routing rules:
  BUILD intent                      → Route.AGENT (build task)
  EDIT intent + active project      → Route.AGENT (edit task)
  EDIT intent + no active project   → Route.CONVERSATION (nothing to edit)
  INFORMATION_QUERY intent          → Route.CONVERSATION (deep-answer conversational pipeline)
  All others                        → Route.CONVERSATION (existing pipeline, unchanged)

With MockLLM (no API keys), intent detection returns CONVERSATION because MockLLM
does not return an "intent" field in its JSON. Development without credentials is
therefore fully preserved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..providers.base import LLMProvider
from .intent import IntentResult, IntentType, detect_intent
from .task import Task, TaskIntent, create_task

log = logging.getLogger("eden.agents.router")


# ---------------------------------------------------------------------------
# Route choices
# ---------------------------------------------------------------------------

class Route(str, Enum):
    CONVERSATION = "conversation"
    AGENT        = "agent"


@dataclass
class RoutingDecision:
    route:  Route
    intent: IntentResult
    task:   Optional[Task]
    reason: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class AgentRouter:
    """Routes incoming messages to either the conversational or agent pipeline.

    BUILD always routes to the agent. EDIT routes to the agent only when a
    project is currently running; otherwise there is nothing to edit and the
    message goes to the conversational pipeline. EXPLAIN, DEMONSTRATE, DEBUG,
    and INFORMATION_QUERY are all handled conversationally — INFORMATION_QUERY
    is passed through with its intent preserved so the conversation handler
    can generate a deeper, knowledge-appropriate response.
    """

    async def route(
        self,
        text: str,
        llm: LLMProvider,
        active_project_summary: Optional[str] = None,
    ) -> RoutingDecision:
        intent = await detect_intent(text, llm, active_project=active_project_summary)

        log.info(
            "routing: intent=%s confidence=%.2f active_project=%s text=%r",
            intent.intent.value,
            intent.confidence,
            bool(active_project_summary),
            text[:60],
        )

        if intent.intent == IntentType.BUILD:
            task = create_task(
                user_request = text,
                intent       = TaskIntent.BUILD,
                app_type     = intent.app_type,
                app_name     = intent.app_name or _default_app_name(intent.app_type),
            )
            log.info("build task created: id=%s app_type=%s", task.id, task.app_type)
            return RoutingDecision(
                route  = Route.AGENT,
                intent = intent,
                task   = task,
                reason = f"BUILD intent (confidence={intent.confidence:.2f})",
            )

        if intent.intent == IntentType.EDIT and active_project_summary:
            task = create_task(
                user_request = text,
                intent       = TaskIntent.EDIT,
            )
            log.info("edit task created: id=%s", task.id)
            return RoutingDecision(
                route  = Route.AGENT,
                intent = intent,
                task   = task,
                reason = f"EDIT intent on active project (confidence={intent.confidence:.2f})",
            )

        if intent.intent == IntentType.INFORMATION_QUERY:
            log.info(
                "information query routed to conversational pipeline (confidence=%.2f)",
                intent.confidence,
            )
            return RoutingDecision(
                route  = Route.CONVERSATION,
                intent = intent,
                task   = None,
                reason = f"INFORMATION_QUERY intent — deep conversational response (confidence={intent.confidence:.2f})",
            )

        # Everything else (incl. EDIT with no active project) → conversation.
        return RoutingDecision(
            route  = Route.CONVERSATION,
            intent = intent,
            task   = None,
            reason = f"{intent.intent.value} intent — conversational pipeline",
        )


def _default_app_name(app_type: Optional[str]) -> str:
    if not app_type:
        return "App"
    return app_type.replace("_", " ").title() + " App"


# Module-level singleton used by main.py
router = AgentRouter()