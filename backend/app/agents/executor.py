"""Executor — performs the real I/O of a build, one discrete phase at a time.

The orchestrator drives two of these phases so it can narrate around each one
and only ever report an outcome after it has actually happened:

    write_project        create directories + write every file
    install_dependencies run the dependency install (npm install)

Each phase emits tool_called / tool_result events and updates Task state. The
executor never calls the LLM and never decides what to build — it acts on an
already-prepared GeneratedProject.

A third phase, ``launch`` (start the dev server as a background process), is
UNUSED — the build pipeline no longer launches anything after install; see
``agents/orchestrator.py``, which stops at "save to workspace". ``launch`` is
kept, dormant, in case a future live-preview feature needs it again (paired
with ``builder/generator.py``'s ``set_launch``/``builder/ports.py``'s
``find_free_port``, also dormant for the same reason).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket

from .. import events
from ..builder.generator import GeneratedProject
from ..agents.task import Task
from ..config import settings
from ..tools import filesystem, shell

log = logging.getLogger("eden.agents.executor")


@dataclass
class ExecutionResult:
    success:     bool
    error:       Optional[str] = None
    dev_process: Optional["asyncio.subprocess.Process"] = None  # type: ignore[name-defined]


def _next_index(task: Task) -> int:
    """A monotonically increasing step index derived from Task progress."""
    return len(task.completed_steps) + len(task.failed_steps)


class Executor:
    """Performs build phases against the sandbox, emitting progress events."""

        # ------------------------------------------------------------------
    # Phase 1 — create directories and write all files
    # ------------------------------------------------------------------
    async def write_project(
        self,
        project: GeneratedProject,
        task: Task,
        websocket: WebSocket,
    ) -> ExecutionResult:

        workspace = project.workspace

        log.info("========== EXECUTOR ==========")
        log.info("Workspace: %s", workspace)
        log.info("Files to write: %d", len(project.files))

        for f in project.files:
            log.info(
                "%s (%d chars)",
                f.path,
                len(f.content)
            )

        for dir_path in project.directories:
            idx = _next_index(task)

            await websocket.send_json(
                events.tool_called(
                    "create_directory",
                    {"path": dir_path},
                    idx,
                    task.id,
                )
            )

            task.begin_step(f"create_directory:{dir_path}")

            result = await filesystem.create_directory(workspace / dir_path)

            if not result.success:
                task.fail_step(f"create_directory:{dir_path}")

                await websocket.send_json(
                    events.tool_result(
                        "create_directory",
                        False,
                        result.error or "",
                        idx,
                        task.id,
                    )
                )

                return ExecutionResult(
                    success=False,
                    error=result.error,
                )

            task.complete_step(f"create_directory:{dir_path}")

            await websocket.send_json(
                events.tool_result(
                    "create_directory",
                    True,
                    result.output,
                    idx,
                    task.id,
                )
            )

        for file in project.files:
            idx = _next_index(task)

            await websocket.send_json(
                events.tool_called(
                    "create_file",
                    {"path": file.path},
                    idx,
                    task.id,
                )
            )

            task.begin_step(f"create_file:{file.path}")

            result = await filesystem.create_file(
                workspace / file.path,
                file.content,
            )

            if not result.success:
                task.fail_step(f"create_file:{file.path}")

                await websocket.send_json(
                    events.tool_result(
                        "create_file",
                        False,
                        result.error or "",
                        idx,
                        task.id,
                    )
                )

                return ExecutionResult(
                    success=False,
                    error=result.error,
                )

            task.complete_step(f"create_file:{file.path}")
            task.record_file(file.path)

            await websocket.send_json(
                events.tool_result(
                    "create_file",
                    True,
                    result.output,
                    idx,
                    task.id,
                )
            )

        # Force Windows to flush timestamps
        for f in project.files:
            try:
                os.utime(project.workspace / f.path, None)
            except Exception:
                pass

        # Give Windows a moment to flush filesystem buffers
        await asyncio.sleep(2)

        return ExecutionResult(success=True)
    # ------------------------------------------------------------------
    # Phase 2 — install dependencies
    # ------------------------------------------------------------------
    async def install_dependencies(
        self,
        project: GeneratedProject,
        task: Task,
        websocket: WebSocket,
    ) -> ExecutionResult:
        cmd = project.install_command
        if not cmd:
            return ExecutionResult(success=True)  # nothing to install

        idx = _next_index(task)
        await websocket.send_json(events.tool_called(
            "run_command", {"command": cmd}, idx, task.id
        ))
        task.begin_step(f"install:{cmd}")
        result = await shell.run_command(cmd, project.workspace, timeout=settings.build_install_timeout)
        if not result.success:
            task.fail_step(f"install:{cmd}")
            await websocket.send_json(events.tool_result(
                "run_command", False,
                (result.error or "") + "\n" + (result.output or "")[-400:],
                idx, task.id,
            ))
            return ExecutionResult(success=False, error=result.error or "dependency install failed")
        task.complete_step(f"install:{cmd}")
        await asyncio.sleep(2)
        task.record_command(cmd)
        await websocket.send_json(events.tool_result(
            "run_command", True, (result.output or "dependencies installed")[-400:], idx, task.id
        ))
        return ExecutionResult(success=True)

    # ------------------------------------------------------------------
    # Phase 3 — launch the dev server (background; does NOT prove it serves)
    # UNUSED — orchestrator.py never calls this. Kept dormant for a possible
    # future live-preview feature (see module docstring).
    # ------------------------------------------------------------------
    async def launch(
        self,
        project: GeneratedProject,
        task: Task,
        websocket: WebSocket,
    ) -> ExecutionResult:
        cmd = project.dev_start_command
        if not cmd:
            return ExecutionResult(success=False, error="no start command was set")

        # ---- Pre-launch diagnostics ----------------------------------------
        workspace = project.workspace
        log.info("=== LAUNCH PRE-CHECK ===")
        log.info("  project.workspace   : %s", workspace)
        log.info("  project.expected_url: %s", project.expected_url)
        log.info("  dev_start_command   : %s", cmd)
        log.info("  workspace exists    : %s", workspace.exists())
        log.info("  workspace absolute  : %s", workspace.is_absolute())

        _KEY_FILES = [
            "package.json",
            "vite.config.js",
            "index.html",
            "src/main.jsx",
            "src/App.jsx",
            "src/styles.css",
        ]
        for f in _KEY_FILES:
            path = workspace / f
            if path.exists():
                log.info(
                    "%s size=%d bytes",
                    f,
                    path.stat().st_size
                )
        for kf in _KEY_FILES:
            path = workspace / kf
            status = "EXISTS" if path.exists() else "MISSING ← !"
            log.info("  [%s] %s", status, kf)

        if workspace.exists():
            all_files = sorted(workspace.rglob("*"))
            log.info("  workspace file listing (%d items):", len(all_files))
            for p in all_files[:60]:
                log.info("    %s", p.relative_to(workspace))
            if len(all_files) > 60:
                log.info("    ... and %d more", len(all_files) - 60)
        else:
            log.error("  WORKSPACE DOES NOT EXIST — files were never written!")
        log.info("=== END PRE-CHECK ===")
        # ---- End diagnostics -----------------------------------------------

        idx = _next_index(task)
        await websocket.send_json(events.tool_called(
            "run_command", {"command": cmd, "background": True}, idx, task.id
        ))
        task.begin_step(f"launch:{cmd}")
        await asyncio.sleep(1)
        try:
            proc = await shell.start_background(cmd, project.workspace)
            await asyncio.sleep(3)
        except Exception as exc:  # noqa: BLE001
            task.fail_step(f"launch:{cmd}")
            await websocket.send_json(events.tool_result(
                "run_command", False, str(exc), idx, task.id
            ))
            return ExecutionResult(success=False, error=str(exc))

        # The process started, but the app is NOT confirmed running yet.
        task.complete_step(f"launch:{cmd}")
        task.record_command(cmd)
        await websocket.send_json(events.tool_result(
            "run_command", True,
            f"dev server process started — not yet verified at {project.expected_url}",
            idx, task.id,
        ))
        return ExecutionResult(success=True, dev_process=proc)
