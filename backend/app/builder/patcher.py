"""File patch engine — applies an EditPlan to the sandbox, safely.

Flow:
  1. Snapshot the files the edit will touch (for rollback).
  2. Validate every proposed file statically.
  3. Only if all pass, write them to disk (Vite hot-reloads them).

The patcher never restarts the dev server, never reinstalls dependencies, and
never touches files outside the edit. Writing over already-running source is all
Vite needs to hot-reload.

Validation happens BEFORE any write, so a bad edit never reaches disk in the
first place. The Snapshot is still returned so the orchestrator can restore even
against a later failure (or a repair attempt that also fails).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from .. import events
from ..agents.edit_planner import EditPlan
from ..builder.rollback import Snapshot
from ..builder.validator import validate_file
from ..tools import filesystem

log = logging.getLogger("eden.builder.patcher")


@dataclass
class PatchResult:
    success:  bool
    snapshot: Snapshot
    changed:  list[str]       = field(default_factory=list)
    error:    str             = ""


async def apply_edit(
    plan:      EditPlan,
    workspace,
    task,
    websocket: WebSocket,
) -> PatchResult:
    """Validate then apply an EditPlan. Returns a PatchResult with a snapshot.

    On any validation failure, nothing is written and ``success`` is False. The
    snapshot always reflects the pre-edit state so the caller can restore.
    """
    paths = plan.touches
    snapshot = Snapshot.capture(workspace, paths)

    # 1. Validate everything up front — a bad edit never reaches disk.
    for edit in plan.edits:
        result = validate_file(edit.path, edit.content)
        if not result.ok:
            log.warning("patch validation failed: %s", result.reason)
            return PatchResult(success=False, snapshot=snapshot, error=result.reason)

    # 2. Write each validated file.
    changed: list[str] = []
    for i, edit in enumerate(plan.edits):
        await websocket.send_json(events.tool_called(
            "edit_file", {"path": edit.path}, i, task.id
        ))
        task.begin_step(f"edit_file:{edit.path}")
        write = await filesystem.create_file(workspace / edit.path, edit.content)
        if not write.success:
            task.fail_step(f"edit_file:{edit.path}")
            await websocket.send_json(events.tool_result(
                "edit_file", False, write.error or "", i, task.id
            ))
            return PatchResult(success=False, snapshot=snapshot,
                               changed=changed, error=write.error or "write failed")
        task.complete_step(f"edit_file:{edit.path}")
        changed.append(edit.path)
        await websocket.send_json(events.tool_result(
            "edit_file", True, write.output, i, task.id
        ))

    return PatchResult(success=True, snapshot=snapshot, changed=changed)
