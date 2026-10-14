"""Shared result type for all tool implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolResult:
    """Outcome of a single tool invocation."""

    success: bool
    output:  str
    error:   Optional[str] = None
