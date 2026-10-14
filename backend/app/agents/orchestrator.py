"""Orchestrator — coordinates the complete BUILD workflow.

Single entry point for BUILD requests. It owns the lifecycle:

    acknowledge → sandbox → plan → generate → write → install → save → complete

Reality rules enforced here:
  - Narration for a stage is emitted only when that stage is genuinely the
    current reality (files are narrated after they are written; installing is
    narrated while npm install is actually running).
  - Any failed phase stops the build immediately and is reported honestly.
  - The pipeline does NOT launch applications, assign ports, open browsers,
    verify rendering, or repair generated UI.
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
from ..builder.sandbox import sandbox_manager
from ..builder.validator import validate_file
from ..builder.version_manager import version_manager
from ..providers.base import LLMProvider, TTSProvider
from ..session import Session

log = logging.getLogger("eden.agents.orchestrator")

_executor = Executor()

# Human-readable pipeline shown to the frontend before execution begins.
_PIPELINE_STEPS = [
    "Design the interface",
    "Generate the application",
    "Write the project files",
    "Install dependencies",
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

        # 4. Plan (LLM) --------------------------------------------------------
        plan = await generate_plan(
            task_id      = task.id,
            app_type     = task.app_type or "application",
            app_name     = app_name,
            user_request = task.user_request,
            features     = decision.intent.features,
            llm          = llm,
            workspace    = sb.root,
        )
        if plan is None:
            await self._fail(
                task, "the design could not be generated",
                ctx, llm, tts, websocket, system_prompt, scope,
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

        # 5. Generate the project (scaffold + app files) -----------------------
        project = from_plan(plan)
        if not project.files:
            await self._fail(
                task, "no project files were produced",
                ctx, llm, tts, websocket, system_prompt, scope,
            )
            return

        # 5b. Validate generated app files before doing anything expensive.
        #     Catches broken LLM output (unbalanced braces, missing default
        #     export, forbidden imports) before npm install wastes time on
        #     bad code.
        for f in project.files:
            if f.path in ("src/App.jsx", "src/styles.css"):
                vr = validate_file(f.path, f.content)
                if not vr.ok:
                    await self._fail(
                        task, f"generated code is invalid: {vr.reason}",
                        ctx, llm, tts, websocket, system_prompt, scope,
                    )
                    return

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

        # 9. Complete — workspace saved, nothing launched ---------------------
        task.mark_completed({"workspace": str(project.workspace)})
        await websocket.send_json(events.task_updated(task.to_dict()))
        await websocket.send_json(
            events.build_complete(
                str(project.workspace),
                plan.app_name,
                task.id,
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
            url         = "",
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