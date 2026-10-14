"""Task model — the central state object for all agentic work.

A Task is created when a build (or other agentic) request arrives and
carries full state throughout the agent lifecycle: status, steps completed
or failed, files generated, commands executed, and the final result.

Phase 1: data model and factory only. Execution phases populate it later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Status and intent enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING    = "pending"      # Created, not yet started
    PLANNING   = "planning"     # Planner is generating the execution plan
    RUNNING    = "running"      # Executor is carrying out plan steps
    EDITING    = "editing"      # Editor is patching an already-running project
    VALIDATING = "validating"   # Validator is checking generated output
    COMPLETED  = "completed"    # All steps done and application is running
    FAILED     = "failed"       # Unrecoverable failure after all recovery attempts
    CANCELLED  = "cancelled"    # Cancelled before completion


class TaskIntent(str, Enum):
    CONVERSATION = "conversation"
    BUILD        = "build"
    EDIT         = "edit"        # Modify the active, already-running project
    EXPLAIN      = "explain"
    DEMONSTRATE  = "demonstrate"
    DEBUG        = "debug"


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """Complete state for a single agentic request.

    Fields are progressively populated as the agent moves through phases:
      Phase 1 — id, user_request, intent, status, app_type, app_name, plan, working_directory
      Phase 2 — generated_files, executed_commands, completed_steps, failed_steps, retry_count
      Phase 3 — final_result
    """

    id:                  str
    user_request:        str
    intent:              TaskIntent
    status:              TaskStatus
    current_step:        Optional[str]
    completed_steps:     list[str]
    failed_steps:        list[str]
    retry_count:         int
    working_directory:   Optional[Path]
    generated_files:     list[str]
    executed_commands:   list[str]
    created_at:          datetime
    updated_at:          datetime
    final_result:        Optional[Any]

    # Populated by intent detector and planner
    app_type:  Optional[str] = None
    app_name:  Optional[str] = None
    plan:      Optional[Any] = None   # typed as Plan in planner.py

    # ---------------------------------------------------------------------------
    # State transitions
    # ---------------------------------------------------------------------------

    def mark_planning(self) -> None:
        self.status     = TaskStatus.PLANNING
        self.updated_at = datetime.utcnow()

    def mark_running(self) -> None:
        self.status     = TaskStatus.RUNNING
        self.updated_at = datetime.utcnow()

    def mark_editing(self) -> None:
        self.status     = TaskStatus.EDITING
        self.updated_at = datetime.utcnow()

    def mark_validating(self) -> None:
        self.status     = TaskStatus.VALIDATING
        self.updated_at = datetime.utcnow()

    def mark_completed(self, result: Any = None) -> None:
        self.status       = TaskStatus.COMPLETED
        self.final_result = result
        self.updated_at   = datetime.utcnow()

    def mark_failed(self, reason: str) -> None:
        self.status       = TaskStatus.FAILED
        self.final_result = {"error": reason}
        self.updated_at   = datetime.utcnow()

    def mark_cancelled(self) -> None:
        self.status     = TaskStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    # ---------------------------------------------------------------------------
    # Step tracking
    # ---------------------------------------------------------------------------

    def begin_step(self, step: str) -> None:
        self.current_step = step
        self.updated_at   = datetime.utcnow()

    def complete_step(self, step: str) -> None:
        self.completed_steps.append(step)
        self.current_step = None
        self.updated_at   = datetime.utcnow()

    def fail_step(self, step: str) -> None:
        self.failed_steps.append(step)
        self.retry_count += 1
        self.current_step = None
        self.updated_at   = datetime.utcnow()

    def record_file(self, path: str) -> None:
        self.generated_files.append(path)
        self.updated_at = datetime.utcnow()

    def record_command(self, cmd: str) -> None:
        self.executed_commands.append(cmd)
        self.updated_at = datetime.utcnow()

    # ---------------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                self.id,
            "user_request":      self.user_request,
            "intent":            self.intent.value,
            "status":            self.status.value,
            "current_step":      self.current_step,
            "completed_steps":   self.completed_steps,
            "failed_steps":      self.failed_steps,
            "retry_count":       self.retry_count,
            "working_directory": str(self.working_directory) if self.working_directory else None,
            "generated_files":   self.generated_files,
            "executed_commands": self.executed_commands,
            "created_at":        self.created_at.isoformat(),
            "updated_at":        self.updated_at.isoformat(),
            "app_type":          self.app_type,
            "app_name":          self.app_name,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_task(
    user_request: str,
    intent:       TaskIntent,
    app_type:     Optional[str] = None,
    app_name:     Optional[str] = None,
) -> Task:
    """Create a new Task in PENDING state."""
    now = datetime.utcnow()
    return Task(
        id                = str(uuid.uuid4()),
        user_request      = user_request,
        intent            = intent,
        status            = TaskStatus.PENDING,
        current_step      = None,
        completed_steps   = [],
        failed_steps      = [],
        retry_count       = 0,
        working_directory = None,
        generated_files   = [],
        executed_commands = [],
        created_at        = now,
        updated_at        = now,
        final_result      = None,
        app_type          = app_type,
        app_name          = app_name,
    )
