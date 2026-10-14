"""Tool registry — infrastructure that future tool implementations plug into.

Phase 1: registry infrastructure and tool descriptor model only.
         Four tools are declared with their schemas; no handlers are bound yet.

Phase 2: bind execution handlers via REGISTRY.bind(name, handler_fn).
         The handler signature is: async def handler(step: PlanStep, sandbox: Sandbox) -> ToolResult

A tool descriptor holds everything the planner and orchestrator need to know
about a tool: what it does, what parameters it accepts, whether it is callable.
The handler is optional — a registered-but-unbound tool is visible to the planner
but will raise an error if the executor tries to call it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("eden.tools.registry")


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass
class ToolDescriptor:
    """Metadata and optional handler for a single tool."""

    name:        str                        # Action string — matches PlanStep.action
    description: str                        # Human-readable; used in planner prompts and logs
    parameters:  dict[str, Any]             # JSON Schema-style parameter specification
    enabled:     bool        = True
    handler:     Optional[Callable] = field(default=None, repr=False)

    def is_callable(self) -> bool:
        """True if this tool has a bound handler and is enabled."""
        return self.handler is not None and self.enabled


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Central registry for all tools available to the coding agent.

    Tools are registered in Phase 1 with metadata only.
    Handlers are bound in Phase 2 when implementations are added.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        """Register a tool descriptor, replacing any existing entry with the same name."""
        if descriptor.name in self._tools:
            log.warning("tool %r already registered — replacing", descriptor.name)
        self._tools[descriptor.name] = descriptor
        log.debug("tool registered: %s (callable=%s)", descriptor.name, descriptor.is_callable())

    def get(self, name: str) -> Optional[ToolDescriptor]:
        """Return the descriptor for a named tool, or None."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDescriptor]:
        """Return all registered tool descriptors."""
        return list(self._tools.values())

    def list_actions(self) -> list[str]:
        """Return all registered action names."""
        return list(self._tools.keys())

    def is_registered(self, action: str) -> bool:
        """True if a tool with this action name has been registered."""
        return action in self._tools

    def is_callable(self, action: str) -> bool:
        """True if a tool is registered, enabled, and has a bound handler."""
        tool = self._tools.get(action)
        return tool is not None and tool.is_callable()

    def bind(self, name: str, handler: Callable) -> None:
        """Bind an execution handler to a registered tool.

        Called in Phase 2 when tool implementations are added.
        Raises KeyError if the tool has not been registered first.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool {name!r} is not registered. Register before binding.")
        tool.handler = handler
        log.info("handler bound to tool: %s", name)

    def describe(self) -> str:
        """One-line summary for logging and diagnostics."""
        callable_count = sum(1 for t in self._tools.values() if t.is_callable())
        return (
            f"ToolRegistry({len(self._tools)} tools registered, "
            f"{callable_count} callable)"
        )

    def __repr__(self) -> str:
        return self.describe()


# ---------------------------------------------------------------------------
# Module-level singleton — Phase 1 tool declarations
# ---------------------------------------------------------------------------

REGISTRY = ToolRegistry()

REGISTRY.register(ToolDescriptor(
    name        = "create_directory",
    description = "Create a directory at the given path within the sandbox, including all parent directories",
    parameters  = {
        "type": "object",
        "properties": {
            "path": {
                "type":        "string",
                "description": "Directory path relative to sandbox root",
            },
        },
        "required": ["path"],
    },
))

REGISTRY.register(ToolDescriptor(
    name        = "create_file",
    description = "Write content to a file within the sandbox, creating parent directories as needed",
    parameters  = {
        "type": "object",
        "properties": {
            "path": {
                "type":        "string",
                "description": "File path relative to sandbox root",
            },
            "content": {
                "type":        "string",
                "description": "Complete file content to write",
            },
        },
        "required": ["path", "content"],
    },
))

REGISTRY.register(ToolDescriptor(
    name        = "run_command",
    description = "Execute a shell command inside the sandbox working directory with a timeout",
    parameters  = {
        "type": "object",
        "properties": {
            "command": {
                "type":        "string",
                "description": "Shell command to execute",
            },
            "timeout_seconds": {
                "type":        "integer",
                "default":     60,
                "description": "Maximum execution time before the process is killed",
            },
        },
        "required": ["command"],
    },
))

REGISTRY.register(ToolDescriptor(
    name        = "open_browser",
    description = "Open a URL in the default system browser",
    parameters  = {
        "type": "object",
        "properties": {
            "url": {
                "type":        "string",
                "description": "URL to open in the browser",
            },
        },
        "required": ["url"],
    },
))
