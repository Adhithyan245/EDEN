"""Planner — converts a build request into a structured execution plan.

Uses a separate, focused system prompt (not EDEN's personality). The model acts
as a front-end engineer and returns only structured JSON.

Reliability strategy: the planner does NOT write the whole project. The React +
Vite scaffold (package.json, vite config, index.html, entrypoint) is fixed and
supplied by builder/template.py. The planner generates only the two files that
are genuinely specific to the request:

    src/App.jsx      the application component
    src/styles.css   its styling

Keeping the model's output to two files keeps it in-budget and dramatically
reduces the chance of a fatal generation error during a live build.

If the model fails to produce a usable App component, ``generate_plan`` returns
None. The orchestrator then reports the failure honestly — it never fabricates a
working build. Reality wins.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import settings
from .intent import IntentType
from ..providers.base import LLMProvider
from ..utils import extract_json

log = logging.getLogger("eden.agents.planner")


# ---------------------------------------------------------------------------
# Plan data model
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """A single action within an execution plan."""

    id:                          int
    action:                      str
    description:                 str
    path:                        Optional[str] = None
    content:                     Optional[str] = None
    command:                     Optional[str] = None
    url:                         Optional[str] = None
    estimated_duration_seconds:  int           = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                         self.id,
            "action":                     self.action,
            "description":                self.description,
            "path":                       self.path,
            "command":                    self.command,
            "url":                        self.url,
            "estimated_duration_seconds": self.estimated_duration_seconds,
        }


@dataclass
class Plan:
    """Structured execution plan for a build request.

    ``workspace`` is set by the sandbox before execution. ``start_command`` and
    ``expected_url`` are placeholders here — the orchestrator finalizes them with
    a real free port at launch time.
    """

    task_id:            str
    app_type:           str
    app_name:           str
    steps:              list[PlanStep]
    start_command:      str
    expected_url:       str
    narration_intro:    str
    narration_complete: str
    workspace:          Optional[Path] = None
    created_at:         datetime       = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id":            self.task_id,
            "app_type":           self.app_type,
            "app_name":           self.app_name,
            "workspace":          str(self.workspace) if self.workspace else None,
            "steps":              [s.to_dict() for s in self.steps],
            "start_command":      self.start_command,
            "expected_url":       self.expected_url,
            "narration_intro":    self.narration_intro,
            "narration_complete": self.narration_complete,
            "step_count":         len(self.steps),
            "created_at":         self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Planner system prompt
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = """\
You are a senior front-end engineer. You build small, complete, working React
applications. Respond with ONE valid JSON object and nothing else — no markdown,
no commentary, no code fences.

You are given a request. Infer what application is being asked for — you are not
restricted to any fixed list. Calculators, to-do lists, attendance trackers,
quizzes, note apps, timers, dashboards, expense trackers, and anything similar
are all in scope. Build a genuinely functional single-page app, not a mock-up.

The project already has its scaffold (package.json, Vite config, index.html, and
the React entrypoint). You only write TWO files:

  src/App.jsx     — the complete application as a default-exported React component
  src/styles.css  — the styling for that component

Return this exact JSON shape:

{
  "app_name": "<short human title, e.g. 'Attendance Tracker'>",
  "app_type": "<one or two word label you infer, e.g. 'attendance'>",
  "app_jsx": "<the complete contents of src/App.jsx>",
  "styles_css": "<the complete contents of src/styles.css>",
  "narration_intro": "<1 sentence EDEN could say as it starts — calm, natural, no jargon>",
  "narration_complete": "<1 sentence EDEN could say once it is confirmed running>"
}

Hard rules for src/App.jsx:
  - Import only from 'react' (e.g. import React, { useState } from 'react').
  - Do NOT import any other package. No axios, no libraries, no icons packages.
  - Do NOT import the CSS file — the entrypoint already imports it. Use className.
  - Provide a single default export: export default function App() { ... }.
  - Make it fully functional using React state. Persist with localStorage only if
    it is natural for the app; otherwise in-memory state is fine.
  - Do NOT call external network APIs. If the app would need live data (e.g. a
    weather dashboard), use realistic built-in sample data instead.
  - The code must run as-is with no edits. No placeholders, no "TODO", no stubs.

Hard rules for src/styles.css:
  - Professional, polished design — this will be projected on a large screen in front of an audience.
  - Dark theme: deep dark background (#0a0e17 or similar), light text (#e2e8f0 or similar).
  - Generous spacing: comfortable padding and gaps. Never cramped or tight.
  - Typography: minimum 1rem body text, 1.25rem+ for headings. Clear visual hierarchy.
  - Interactive elements (buttons, inputs): visible hover states with smooth transitions (0.15s ease).
  - Buttons: solid fill with a distinct accent colour (teal, blue, or purple); clear hover darkening.
  - Cards, panels, inputs: rounded corners (0.5rem+), subtle borders or box-shadows for depth.
  - Layout: centred, max-width around 420–520px for single-column apps (wider for dashboards).
  - Every className used in App.jsx must have a corresponding style. No missing or orphaned rules.
  - Use CSS custom properties (--var) for accent colours so the theme feels coherent.

Narration rules:
  - Natural spoken phrasing, confident and brief.
  - No jargon: no "scaffolding", "bootstrapping", "component", "render", "state management".
  - No service language: no "Certainly", "Of course", "Let me help you".
"""


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

async def generate_plan(
    task_id:      str,
    app_type:     str,
    app_name:     str,
    user_request: str,
    features:     list[str],
    llm:          LLMProvider,
    workspace:    Optional[Path] = None,
    repair_error: Optional[str] = None,
) -> Optional[Plan]:
    """Generate a Plan for a build request, or None if generation fails.

    Uses settings.model_builder. Returns None (never a fake plan) when the model
    cannot produce a usable App component, so the orchestrator can be honest.
    When ``repair_error`` is set, the model is told why its previous attempt
    was rejected so the retry can avoid the same mistake.
    """
    feature_hint = f"\nSpecific features requested: {', '.join(features)}" if features else ""
    user_prompt = (
        f"Request: {user_request}\n"
        f"Suggested name: {app_name}\n"
        f"Suggested type: {app_type}"
        f"{feature_hint}"
    )
    if repair_error:
        user_prompt += (
            "\n\nYour previous attempt was rejected: "
            f"{repair_error}\n"
            "Return a corrected, complete response that fixes this problem."
        )

    try:
        raw_parts: list[str] = []
        async for chunk in llm.stream_reply(
            [{"role": "user", "content": user_prompt}],
            _PLANNER_SYSTEM,
            model=settings.model_builder,
            # BUILD gets the large output budget: whole files, JSON-escaped.
            intent=IntentType.BUILD,
        ):
            raw_parts.append(chunk)
            if len("".join(raw_parts)) > 60000:  # generous; App.jsx + css can be large
                break

        raw = "".join(raw_parts).strip()
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("planner generation failed (%s)", exc)
        return None

    app_jsx    = str(data.get("app_jsx") or "").strip()
    styles_css = str(data.get("styles_css") or "").strip()

    # Reality check: without a usable App component there is nothing to run.
    if "export default" not in app_jsx:
        log.warning("planner returned no usable App component — aborting")
        return None

    resolved_name = str(data.get("app_name") or app_name or "App").strip()
    resolved_type = str(data.get("app_type") or app_type or "application").strip()

    steps = [
        PlanStep(
            id=0,
            action="create_file",
            description="Write the application component",
            path="src/App.jsx",
            content=app_jsx,
            estimated_duration_seconds=2,
        ),
        PlanStep(
            id=1,
            action="create_file",
            description="Write the styles",
            path="src/styles.css",
            content=styles_css or _DEFAULT_CSS,
            estimated_duration_seconds=1,
        ),
    ]

    return Plan(
        task_id            = task_id,
        app_type           = resolved_type,
        app_name           = resolved_name,
        workspace          = workspace,
        steps              = steps,
        start_command      = "npm run dev",  # placeholder; orchestrator sets the port
        expected_url       = "http://localhost:5173",  # placeholder; overwritten
        narration_intro    = str(data.get("narration_intro") or "").strip(),
        narration_complete = str(data.get("narration_complete") or "").strip(),
    )


_DEFAULT_CSS = """\
:root { color-scheme: dark; }
body { margin: 0; font-family: system-ui, sans-serif; background: #0b0f14; color: #e6edf3; }
#root { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
"""
