"""Edit orchestrator — applies an iterative change to the active project.

This is the editing counterpart to Orchestrator. It works against the project
that was built and saved to its workspace, and it does exactly what a careful
engineer would do with no server running:

    read current files → plan a minimal edit → validate → patch → confirm the
    workspace is still an intact project → acknowledge, honestly.

It NEVER rebuilds, reinstalls, launches a dev server, or opens a browser.
Writing to the workspace is the entire edit — there is nothing to hot-reload
and nothing running to verify.

Safety:
  - Static validation happens before anything is written (in the patcher).
  - On validation failure, one automatic repair is attempted with the error as
    context. If that also fails, the previous file contents are restored so
    the workspace returns to its last working state.
  - Success is acknowledged only after the workspace is confirmed intact
    (package.json present, src/ present, edited files on disk). No faked
    success, no stack traces exposed to the audience.
"""

from __future__ import annotations

import logging

from fastapi import WebSocket

from .. import events
from ..agents.edit_planner import EditPlan, generate_edit_plan
from ..agents.narrator import narrate_stage
from ..agents.router import RoutingDecision
from ..builder.active_project import ActiveProject, project_manager
from ..builder.patcher import apply_edit
from ..builder.validator import validate_workspace
from ..builder.version_manager import version_manager
from ..providers.base import LLMProvider, TTSProvider
from ..session import Session
from ..tools import filesystem

log = logging.getLogger("eden.agents.edit_orchestrator")

# Source files we read for edit context and allow the editor to change.
_READABLE_SUFFIXES = (".jsx", ".tsx", ".js", ".ts", ".css")


class EditOrchestrator:
    """Drives one iterative edit of the active project."""

    async def run(
        self,
        websocket: WebSocket,
        session: Session,
        decision: RoutingDecision,
        llm: LLMProvider,
        tts: TTSProvider,
        system_prompt: str,
    ) -> None:
        task = decision.task
        if task is None:
            log.error("edit orchestrator invoked without a task")
            return

        session_id = str(id(session))
        project = project_manager.get(session_id)
        if project is None:
            # Router should prevent this, but stay honest if it happens.
            log.warning("edit requested with no active project")
            return

        scope   = session.audience_scope
        request = task.user_request
        ctx     = {"app_name": project.app_name, "change": request}

        # Undo / redo are version operations, not LLM edits — handle up front.
        edit_op = getattr(decision.intent, "edit_op", "change")
        if edit_op in ("undo", "redo"):
            await self._version_op(edit_op, task, project, session,
                                   llm, tts, websocket, system_prompt, scope)
            return

        # 1. Acknowledge (reality: nothing changed yet) -----------------------
        await websocket.send_json(events.state(events.State.THINKING))
        await narrate_stage("edit_ack", ctx, llm, tts, websocket, system_prompt, scope)

        # 2. Read the current source files for context ------------------------
        current_files = await self._read_sources(project)

        # 3. Plan a minimal edit ----------------------------------------------
        plan = await generate_edit_plan(project.summary(), request, current_files, llm)
        if plan is None:
            await self._fail(task, project, "I couldn't work out that change", ctx,
                             llm, tts, websocket, system_prompt, scope, restored=False)
            return

        if plan.is_empty:
            # Honest: nothing needed changing.
            await narrate_stage("edit_none", ctx, llm, tts, websocket, system_prompt, scope)
            project.note(f"No change needed for: {request}")
            session.add_assistant(f"[no change needed for '{request}' on {project.app_name}]")
            return

        await websocket.send_json(events.edit_started(
            task.id, project.app_name, plan.summary, plan.touches
        ))
        task.mark_editing()
        await websocket.send_json(events.task_updated(task.to_dict()))
        ctx["change"] = plan.summary  # narrate the concrete change from here on

        # 4. Narrate editing + apply (validate → patch) -----------------------
        await narrate_stage("editing", ctx, llm, tts, websocket, system_prompt, scope)
        result = await apply_edit(plan, project.workspace, task, websocket)

        # 5. One repair attempt on validation failure -------------------------
        if not result.success:
            log.info("edit failed validation (%s) — attempting one repair", result.error)
            repair = await generate_edit_plan(
                project.summary(), request, current_files, llm, repair_error=result.error
            )
            if repair and not repair.is_empty:
                result = await apply_edit(repair, project.workspace, task, websocket)
                if result.success:
                    plan = repair
            if not result.success:
                result.snapshot.restore()  # back to last working state
                await self._fail(task, project, "the change didn't hold", ctx,
                                 llm, tts, websocket, system_prompt, scope, restored=True)
                return

        # 6. Validate the workspace is still an intact project (no server to
        #    verify against — the edit either landed on disk cleanly or it
        #    didn't) ------------------------------------------------------
        task.mark_validating()
        await websocket.send_json(events.task_updated(task.to_dict()))
        wv = validate_workspace(project.workspace, result.changed)
        if not wv.ok:
            result.snapshot.restore()
            await self._fail(task, project, wv.reason or "the workspace no longer looks valid",
                             ctx, llm, tts, websocket, system_prompt, scope, restored=True)
            return

        # 7. Complete — saved to the workspace, nothing running to reopen ----
        task.mark_completed({"workspace": str(project.workspace), "change": plan.summary})
        await websocket.send_json(events.task_updated(task.to_dict()))
        for path in result.changed:
            if path not in project.files:
                project.files.append(path)
        project.note(f"Edited: {plan.summary}")
        # Record this as a new version so it can be undone later.
        version_manager.record(project, plan.summary)
        await websocket.send_json(events.edit_complete(
            task.id, project.app_name, str(project.workspace), result.changed
        ))

        complete_ctx = {"app_name": project.app_name, "change": plan.summary,
                        "fallback": plan.narration}
        await narrate_stage("edit_complete", complete_ctx, llm, tts, websocket, system_prompt, scope)
        session.add_assistant(f"[edited {project.app_name}: {plan.summary}]")
        log.info("edit complete on %s: %s", project.app_name, plan.summary)

    # ------------------------------------------------------------------
    async def _version_op(
        self,
        op: str,
        task,
        project: ActiveProject,
        session: Session,
        llm: LLMProvider,
        tts: TTSProvider,
        websocket: WebSocket,
        system_prompt: str,
        scope: str,
    ) -> None:
        """Undo or redo — restore a stored version's files to the workspace."""
        ctx = {"app_name": project.app_name}
        await websocket.send_json(events.state(events.State.THINKING))
        task.mark_editing()
        await websocket.send_json(events.task_updated(task.to_dict()))

        snap = version_manager.undo(project) if op == "undo" else version_manager.redo(project)
        if snap is None:
            # Nothing to move to — honest, no false claim.
            task.mark_completed({"noop": True})
            await websocket.send_json(events.task_updated(task.to_dict()))
            await narrate_stage("version_none", ctx, llm, tts, websocket, system_prompt, scope)
            project.note(f"{op}: nothing to restore")
            session.add_assistant(f"[{op} requested on {project.app_name}: nothing to restore]")
            return

        # The files were rewritten; confirm the workspace is still intact.
        task.mark_validating()
        await websocket.send_json(events.task_updated(task.to_dict()))
        wv = validate_workspace(project.workspace)
        if not wv.ok:
            await self._fail(task, project, wv.reason or "the workspace no longer looks valid",
                             ctx, llm, tts, websocket, system_prompt, scope, restored=False)
            return

        task.mark_completed({"workspace": str(project.workspace), "version": snap.label})
        await websocket.send_json(events.task_updated(task.to_dict()))
        project.note(f"{op} → {snap.label}")
        await websocket.send_json(
            events.version_restored(task.id, op, snap.label, str(project.workspace))
        )
        await narrate_stage("undo_done" if op == "undo" else "redo_done",
                            ctx, llm, tts, websocket, system_prompt, scope)
        session.add_assistant(f"[{op} on {project.app_name} → {snap.label}]")
        log.info("%s complete on %s → %s", op, project.app_name, snap.label)

    # ------------------------------------------------------------------
    async def _read_sources(self, project: ActiveProject) -> dict[str, str]:
        """Read the app's source files (under src/) as edit context."""
        files: dict[str, str] = {}
        src = project.workspace / "src"
        if not src.exists():
            # Fall back to the recorded editable files.
            for rel in project.editable:
                r = await filesystem.read_file(project.abspath(rel))
                if r.success:
                    files[rel] = r.output
            return files

        for p in sorted(src.rglob("*")):
            if p.is_file() and p.suffix.lower() in _READABLE_SUFFIXES:
                rel = p.relative_to(project.workspace).as_posix()
                r = await filesystem.read_file(p)
                if r.success:
                    files[rel] = r.output
        return files

    # ------------------------------------------------------------------
    async def _fail(
        self,
        task,
        project: ActiveProject,
        reason: str,
        ctx: dict,
        llm: LLMProvider,
        tts: TTSProvider,
        websocket: WebSocket,
        system_prompt: str,
        scope: str,
        restored: bool,
    ) -> None:
        log.error("edit failed (task=%s): %s (restored=%s)", task.id, reason, restored)
        task.mark_failed(reason)
        await websocket.send_json(events.task_updated(task.to_dict()))
        await websocket.send_json(events.edit_failed(task.id, reason, restored))
        project.note(f"Edit failed ({reason}); restored={restored}.")
        stage = "edit_failed" if restored else "failed"
        fail_ctx = {**ctx, "reason": reason}
        await narrate_stage(stage, fail_ctx, llm, tts, websocket, system_prompt, scope)


# Module-level singleton
edit_orchestrator = EditOrchestrator()
