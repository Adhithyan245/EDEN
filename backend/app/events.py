"""The EDEN event protocol.

The backend never returns a single answer — it streams a sequence of typed
events to the frontend, which renders each one. This module is the single
source of truth for event shapes on the Python side; `frontend/src/lib/events.ts`
mirrors it on the TypeScript side.

Response modes:
  chat        — short conversational reply; display == voice
  information — knowledge/research response; display may be longer than voice
  build       — build pipeline narration
  error       — failure narration
"""

from __future__ import annotations

from typing import Any, Optional


# EDEN's high-level states (drive the avatar + status panel).
class State:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# Response mode constants — tell the frontend what kind of response this is.
# Used in reply_done and response_ready so the UI can render accordingly.
class ResponseMode:
    CHAT        = "chat"
    INFORMATION = "information"
    BUILD       = "build"
    TASK        = "task"
    ERROR       = "error"


def event(type_: str, **data: Any) -> dict[str, Any]:
    """Build an event payload for the wire."""
    return {"type": type_, **data}


# Convenience builders for the events used so far. More are added as features land.
def ready(mode: str, llm: str, tts: str, user_name: str) -> dict[str, Any]:
    return event("ready", mode=mode, llm=llm, tts=tts, user_name=user_name)


def state(name: str) -> dict[str, Any]:
    return event("state", state=name)


def token(text: str) -> dict[str, Any]:
    return event("token", text=text)


def reply_done(
    text: str,
    *,
    voice_response: Optional[str] = None,
    response_mode: str = ResponseMode.CHAT,
) -> dict[str, Any]:
    """Emitted when the full assistant reply has been streamed.

    ``text`` is always the complete display text shown on screen.
    ``voice_response`` carries the shorter spoken summary for INFORMATION_QUERY
    responses; when omitted or None it defaults to ``text`` so the frontend
    can always use ``voice_response`` for TTS without branching.
    ``response_mode`` tells the frontend how to render the response.
    """
    return event(
        "reply_done",
        text=text,
        voice_response=voice_response if voice_response is not None else text,
        response_mode=response_mode,
    )


def response_ready(
    response: str,
    *,
    voice_response: Optional[str] = None,
    response_mode: str = ResponseMode.CHAT,
    sources: Optional[list] = None,
) -> dict[str, Any]:
    """Emitted once per completed conversational turn (chat or information).

    This is the structured counterpart to ``reply_done``/``token`` that the
    frontend's presentation reducer consumes to populate ``displayResponse``,
    ``voiceResponse``, ``responseMode``, and ``sources``. It is additive —
    the token stream and ``reply_done`` are still sent unchanged for backward
    compatibility with any consumer that only understands the original flow.

    ``response`` is the full text for visual display. ``voice_response`` is the
    condensed spoken variant (falls back to ``response`` when omitted, so the
    frontend can always use it for TTS without branching). ``sources`` carries
    research citations (title/url/snippet) and is only meaningful when
    ``response_mode`` is ``ResponseMode.INFORMATION``.
    """
    return event(
        "response_ready",
        response=response,
        voice_response=voice_response if voice_response is not None else response,
        response_mode=response_mode,
        sources=sources or [],
    )


def speak(text: str) -> dict[str, Any]:
    """Ask the browser to voice `text` with its built-in SpeechSynthesis."""
    return event("speak", text=text)


def speech_audio(audio_b64: str, mime: str = "audio/mpeg") -> dict[str, Any]:
    """Server-generated audio (e.g. ElevenLabs) for the browser to play."""
    return event("speech_audio", audio_b64=audio_b64, mime=mime)


def emotion(name: str) -> dict[str, Any]:
    """Signal the current emotional state of EDEN for avatar animation."""
    return event("emotion", emotion=name)


def error(message: str) -> dict[str, Any]:
    return event("error", message=message)


def pong() -> dict[str, Any]:
    return event("pong")


# ---------------------------------------------------------------------------
# Agent / builder events — surfaced by the routing layer
# ---------------------------------------------------------------------------

def agent_routing(route: str, intent: str, confidence: float) -> dict[str, Any]:
    """Emitted when the router has decided which pipeline will handle a message."""
    return event("agent_routing", route=route, intent=intent, confidence=confidence)


def task_created(task: dict) -> dict[str, Any]:
    """Emitted when a new Task is created for an agentic request."""
    return event("task_created", task=task)


def task_updated(task: dict) -> dict[str, Any]:
    """Emitted whenever the Task status or step tracking changes."""
    return event("task_updated", task=task)


def plan_ready(task_id: str, steps: list, app_name: str, app_type: str) -> dict[str, Any]:
    """Emitted when the Planner has generated a structured execution plan.

    ``steps`` is a list of human-readable descriptions (one per PlanStep) so
    the frontend can show the pipeline before execution begins.
    """
    return event(
        "plan_ready",
        task_id=task_id,
        steps=steps,
        app_name=app_name,
        app_type=app_type,
        step_count=len(steps),
    )


# ---------------------------------------------------------------------------
# Build lifecycle events — emitted by agents/orchestrator.py. The pipeline
# generates and saves a project to its workspace; it does not launch a dev
# server, assign a port, or open a browser.
# ---------------------------------------------------------------------------

def build_started(app_type: str, app_name: str, task_id: str) -> dict[str, Any]:
    """Emitted when the orchestrator begins executing a build plan."""
    return event("build_started", app_type=app_type, app_name=app_name, task_id=task_id)


def tool_called(tool: str, args: dict, step_index: int, task_id: str) -> dict[str, Any]:
    """Emitted immediately before a tool is invoked."""
    return event("tool_called", tool=tool, args=args, step_index=step_index, task_id=task_id)


def tool_result(tool: str, success: bool, output: str, step_index: int, task_id: str) -> dict[str, Any]:
    """Emitted immediately after a tool returns."""
    return event(
        "tool_result",
        tool=tool,
        success=success,
        output=output,
        step_index=step_index,
        task_id=task_id,
    )


def build_narrate(text: str, task_id: str) -> dict[str, Any]:
    """EDEN speaks a narration during a build (handled like speech_audio on the frontend)."""
    return event("build_narrate", text=text, task_id=task_id)


def build_complete(workspace: str, app_name: str, task_id: str,
                   preview_url: str | None = None) -> dict[str, Any]:
    """Emitted when the project has been generated and saved to its workspace directory.

    ``url`` is included as a legacy alias (set to ``workspace``) so any consumer
    still reading the pre-workspace field shape does not silently break.
    ``preview_url`` is the backend-relative path of the compiled app.
    """
    return event(
        "build_complete",
        workspace=workspace,
        app_name=app_name,
        task_id=task_id,
        url=workspace,
        preview_url=preview_url,
    )


def build_failed(reason: str, used_fallback: bool, task_id: str) -> dict[str, Any]:
    """Emitted when a build could not complete, even after recovery attempts."""
    return event("build_failed", reason=reason, used_fallback=used_fallback, task_id=task_id)


# ---------------------------------------------------------------------------
# Edit events — iterative changes to the active project.
# Individual file edits reuse tool_called / tool_result with tool="edit_file".
# ---------------------------------------------------------------------------

def edit_started(task_id: str, app_name: str, summary: str, files: list) -> dict[str, Any]:
    """Emitted when EDEN begins editing the active project."""
    return event("edit_started", task_id=task_id, app_name=app_name, summary=summary, files=files)


def edit_complete(task_id: str, app_name: str, workspace: str, files: list,
                  preview_url: str | None = None) -> dict[str, Any]:
    """Emitted when an edit has been applied and validated on disk.

    ``url`` is included as a legacy alias (set to ``workspace``) since the edit
    pipeline no longer runs against a live dev server — there is nothing left
    to verify at a URL, only a workspace to confirm is intact.
    """
    return event(
        "edit_complete",
        task_id=task_id,
        app_name=app_name,
        workspace=workspace,
        url=workspace,
        files=files,
        preview_url=preview_url,
    )


def edit_failed(task_id: str, reason: str, restored: bool) -> dict[str, Any]:
    """Emitted when an edit could not be made safely (and was rolled back)."""
    return event("edit_failed", task_id=task_id, reason=reason, restored=restored)


# ---------------------------------------------------------------------------
# Collaboration events — clarification, version history, proactive suggestions.
# ---------------------------------------------------------------------------

def clarification_requested(question: str) -> dict[str, Any]:
    """Emitted when EDEN asks one clarifying question before building."""
    return event("clarification_requested", question=question)


def version_restored(task_id: str, action: str, label: str, workspace: str,
                     preview_url: str | None = None) -> dict[str, Any]:
    """Emitted after an undo/redo restores a previous version of the project.

    ``action`` is "undo" or "redo"; ``label`` describes the version restored to.
    ``url`` is a legacy alias (set to ``workspace``) — restoring a version now
    means rewriting files in the workspace, not confirming a live reload.
    """
    return event(
        "version_restored",
        task_id=task_id,
        action=action,
        label=label,
        workspace=workspace,
        url=workspace,
        preview_url=preview_url,
    )


def suggestion(text: str) -> dict[str, Any]:
    """Emitted when EDEN offers a proactive improvement suggestion."""
    return event("suggestion", text=text)


# ---------------------------------------------------------------------------
# Render-verification events — KEPT FOR FUTURE, currently unemitted.
#
# No code path emits these: the build pipeline no longer launches a dev server
# or opens a browser (see agents/orchestrator.py), so there is nothing to run
# a headless render check against. They are the event counterpart to
# agents/render_verifier.py and agents/repairer.py, which are dormant for the
# same reason — kept together as one unit in case a future live-preview
# feature reintroduces a running server to check and repair against. If that
# never happens, this whole trio (these events + the two agent modules) can
# be removed together.
# ---------------------------------------------------------------------------

def render_verifying(url: str, task_id: str) -> dict[str, Any]:
    """Emitted when the headless browser check begins (after HTTP verify passes)."""
    return event("render_verifying", url=url, task_id=task_id)


def render_verified(url: str, task_id: str) -> dict[str, Any]:
    """Emitted when the app rendered successfully with no fatal console errors."""
    return event("render_verified", url=url, task_id=task_id)


def render_failed(errors: list, error_summary: str, task_id: str) -> dict[str, Any]:
    """Emitted when the render check detected a blank screen or fatal errors."""
    return event("render_failed", errors=errors, error_summary=error_summary, task_id=task_id)


def render_repairing(attempt: int, error_summary: str, task_id: str) -> dict[str, Any]:
    """Emitted when EDEN is rewriting App.jsx to fix a render failure."""
    return event("render_repairing", attempt=attempt, error_summary=error_summary, task_id=task_id)