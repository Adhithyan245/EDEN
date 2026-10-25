"""Orchestrator — coordinates the complete BUILD workflow.

Single entry point for BUILD requests. It owns the lifecycle:

    acknowledge → sandbox → plan → generate → validate (one repair) → write
    → install → save → complete

Reality rules enforced here:
  - Narration for a stage is emitted only when that stage is genuinely the
    current reality (files are narrated after they are written; installing is
    narrated while npm install is actually running).
  - Any failed phase stops the build immediately and is reported honestly.
  - Generated code is checked twice: statically before anything is written,
    and by a real ``vite build`` after install. Each check allows one repair.
  - The pipeline does NOT launch dev servers, assign ports, or open browsers;
    the compiled app is served as static files at its preview URL.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from .. import events
from ..agents.executor import Executor
from ..agents.narrator import narrate_stage
from ..agents.planner import generate_plan
from ..agents.router import RoutingDecision
from ..builder.active_project import ActiveProject, project_manager
from ..builder.generator import from_plan, GeneratedProject
from ..builder.preview import publish
from ..builder.sandbox import sandbox_manager
from ..builder.validator import validate_file
from ..builder.version_manager import version_manager
from ..providers.base import LLMProvider, TTSProvider
from ..session import Session
from ..tools import filesystem

log = logging.getLogger("eden.agents.orchestrator")

_executor = Executor()

# How many times a rejected generation is regenerated before the build fails.
_MAX_BUILD_REPAIRS = 1


def _check_generation(plan) -> str | None:
    """Return why a generated plan is unusable, or None if it can be built.

    Catches broken LLM output (no plan, unbalanced braces, missing default
    export, forbidden imports) before npm install wastes time on bad code.
    """
    if plan is None:
        return "the design could not be generated"
    project = from_plan(plan)
    if not project.files:
        return "no project files were produced"
    for f in project.files:
        if f.path in ("src/App.jsx", "src/styles.css"):
            vr = validate_file(f.path, f.content)
            if not vr.ok:
                return f"generated code is invalid: {vr.reason}"
    return None


async def compile_step(workspace, task, websocket):
    """Run the compile check as a visible tool step. Returns (result, preview_url)."""
    idx = len(task.completed_steps) + len(task.failed_steps)
    await websocket.send_json(events.tool_called(
        "run_command", {"command": "npm run build"}, idx, task.id
    ))
    task.begin_step("compile:npm run build")
    result, preview_url = await publish(workspace)
    if result.ok:
        task.complete_step("compile:npm run build")
    else:
        task.fail_step("compile:npm run build")
    await websocket.send_json(events.tool_result(
        "run_command", result.ok, "compiled" if result.ok else result.error[-400:], idx, task.id
    ))
    return result, preview_url


async def _rewrite_app_files(plan, project) -> bool:
    """Overwrite the planner-owned files with a repaired plan's versions."""
    for f in from_plan(plan).files:
        if f.path in ("src/App.jsx", "src/styles.css"):
            r = await filesystem.create_file(project.workspace / f.path, f.content)
            if not r.success:
                return False
    return True

# Human-readable pipeline shown to the frontend before execution begins.
_PIPELINE_STEPS = [
    "Design the interface",
    "Generate the application",
    "Write the project files",
    "Install dependencies",
    "Compile the app",
    "Save project",
]


class Orchestrator:
    """Drives the full BUILD workflow from RoutingDecision to a saved workspace."""

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
            log.error("orchestrator invoked without a task")
            return

        # A build requested during a live session is a public moment.
        scope = session.audience_scope
        app_name = task.app_name or "the app"
        ctx = {"app_name": app_name}

        # 1. Acknowledge the request (reality: nothing built yet) --------------
        await websocket.send_json(events.state(events.State.THINKING))
        await narrate_stage("acknowledged", ctx, llm, tts, websocket, system_prompt, scope)

        # 2. Kill previous dev server for this session (if any) ---------------
        prev = project_manager.get(str(id(session)))
        if prev is not None and prev.dev_process is not None:
            try:
                prev.dev_process.kill()
                log.info(
                    "killed previous dev server for session (pid=%s)",
                    getattr(prev.dev_process, "pid", "?"),
                )
            except Exception:
                pass

        # 3. Sandbox -----------------------------------------------------------
        sb = sandbox_manager.create(str(id(session)), app_name)
        task.working_directory = sb.root
        task.mark_planning()
        await websocket.send_json(events.task_updated(task.to_dict()))

        # 4–5b. Plan (LLM) → generate → validate, with one repair attempt ------
        #       A rejected generation is retried once with the rejection reason
        #       as context, mirroring the edit pipeline's single repair.
        plan, project, failure = None, None, None
        for attempt in range(1 + _MAX_BUILD_REPAIRS):
            plan = await generate_plan(
                task_id      = task.id,
                app_type     = task.app_type or "application",
                app_name     = app_name,
                user_request = task.user_request,
                features     = decision.intent.features,
                llm          = llm,
                workspace    = sb.root,
                repair_error = failure,
            )
            failure = _check_generation(plan)
            if failure is None:
                project = from_plan(plan)
                break
            log.info("build generation rejected (attempt %d): %s", attempt + 1, failure)

        if failure is not None:
            await self._fail(
                task, failure, ctx, llm, tts, websocket, system_prompt, scope,
            )
            return

        task.plan = plan
        # The planner may refine the name/type — adopt it everywhere downstream.
        app_name      = plan.app_name
        task.app_name = plan.app_name
        task.app_type = plan.app_type
        ctx = {"app_name": app_name}

        await websocket.send_json(events.plan_ready(
            task_id  = task.id,
            steps    = _PIPELINE_STEPS,
            app_name = plan.app_name,
            app_type = plan.app_type,
        ))

        # 6. Signal build start -----------------------------------------------
        await websocket.send_json(events.build_started(plan.app_type, plan.app_name, task.id))
        task.mark_running()
        await websocket.send_json(events.task_updated(task.to_dict()))

        # 7. Write files -------------------------------------------------------
        write = await _executor.write_project(project, task, websocket)
        if not write.success:
            await self._fail(
                task, "the project files could not be written",
                ctx, llm, tts, websocket, system_prompt, scope,
            )
            return

        # 8. Install dependencies — narrate WHILE it genuinely runs -----------
        if project.has_dependencies:
            install_task = asyncio.create_task(
                _executor.install_dependencies(project, task, websocket)
            )
            await narrate_stage("installing", ctx, llm, tts, websocket, system_prompt, scope)
            install = await install_task
            if not install.success:
                await self._fail(
                    task, "the dependencies could not be installed",
                    ctx, llm, tts, websocket, system_prompt, scope,
                )
                return

        # 9. Compile (vite build) — the real verifier. One repair on failure,
        #    with the compiler output as context. -----------------------------
        task.mark_validating()
        await websocket.send_json(events.task_updated(task.to_dict()))
        compiled, preview_url = await compile_step(project.workspace, task, websocket)
        if not compiled.ok:
            log.info("build failed to compile — attempting one repair: %s", compiled.error[:200])
            repaired = await generate_plan(
                task_id      = task.id,
                app_type     = plan.app_type,
                app_name     = plan.app_name,
                user_request = task.user_request,
                features     = decision.intent.features,
                llm          = llm,
                workspace    = sb.root,
                repair_error = f"the app failed to compile:\n{compiled.error}",
            )
            if _check_generation(repaired) is None and await _rewrite_app_files(repaired, project):
                plan = repaired
                compiled, preview_url = await compile_step(project.workspace, task, websocket)
        if not compiled.ok:
            await self._fail(
                task, "the generated app did not compile",
                ctx, llm, tts, websocket, system_prompt, scope,
            )
            return

        # 10. Complete — saved and compiled; preview served as static files ----
        task.mark_completed({"workspace": str(project.workspace), "preview_url": preview_url})
        await websocket.send_json(events.task_updated(task.to_dict()))
        await websocket.send_json(
            events.build_complete(
                str(project.workspace),
                plan.app_name,
                task.id,
                preview_url,
            )
        )

        # Remember this as the active project so it can be edited from here on.
        active = ActiveProject(
            task_id     = task.id,
            app_name    = plan.app_name,
            app_type    = plan.app_type,
            framework   = project.stack,
            workspace   = project.workspace,
            port        = 0,
            url         = preview_url or "",
            files       = project.file_paths,
            dev_process = None,
            plan        = plan,
        )
        active.note(f"Built {plan.app_name} and saved to {project.workspace}")
        project_manager.set(str(id(session)), active)

        # Seed the undo/redo timeline with the freshly built version (v0).
        version_manager.init(active)

        complete_ctx = {"app_name": app_name, "fallback": plan.narration_complete}
        await narrate_stage("complete", complete_ctx, llm, tts, websocket, system_prompt, scope)

        # Internal continuity note (not spoken) so later turns know what exists.
        session.add_assistant(
            f"[{app_name} was built and saved at {project.workspace}]"
        )
        log.info("project saved: %s at %s (task=%s)", app_name, project.workspace, task.id)

        # A collaborative engineer offers a next step — at most one, easy to ignore.
        suggestion = await narrate_stage(
            "suggest", {"app_name": app_name, "app_type": plan.app_type},
            llm, tts, websocket, system_prompt, scope,
        )
        if suggestion:
            await websocket.send_json(events.suggestion(suggestion))

    # ------------------------------------------------------------------
    async def _fail(
        self,
        task,
        reason: str,
        ctx: dict,
        llm: LLMProvider,
        tts: TTSProvider,
        websocket: WebSocket,
        system_prompt: str,
        scope: str,
    ) -> None:
        log.error("build failed (task=%s): %s", task.id, reason)
        task.mark_failed(reason)
        await websocket.send_json(events.task_updated(task.to_dict()))
        await websocket.send_json(events.build_failed(reason, False, task.id))
        fail_ctx = {**ctx, "reason": reason}
        await narrate_stage("failed", fail_ctx, llm, tts, websocket, system_prompt, scope)


# Module-level singleton
orchestrator = Orchestrator()