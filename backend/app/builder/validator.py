"""Lightweight static validation for edited source files.

A broken React file does not stop Vite's dev server from serving ``/`` (it still
returns the static index.html), so an HTTP check alone cannot catch a bad edit.
Static validation is therefore the real guard before we let Vite hot-reload a
change in front of an audience.

These checks are intentionally conservative — they catch the common ways an LLM
edit breaks a file (truncation, unbalanced braces, a missing default export, a
forbidden import) without being so strict that they reject valid code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    ok:     bool
    reason: str = ""


def validate_file(path: str, content: str) -> ValidationResult:
    """Validate a single edited file by its path/extension."""
    lower = path.lower()
    if not content.strip():
        return ValidationResult(False, f"{path} is empty")

    if lower.endswith((".jsx", ".tsx", ".js", ".ts")):
        return _validate_js(path, content)
    if lower.endswith(".css"):
        return _validate_css(path, content)
    # Unknown file types are accepted as-is.
    return ValidationResult(True)


def _validate_js(path: str, content: str) -> ValidationResult:
    # Balanced brackets (ignoring those inside strings/comments would be ideal,
    # but a straight count reliably catches truncation and the usual LLM slips).
    for open_ch, close_ch, label in (("{", "}", "braces"),
                                     ("(", ")", "parentheses"),
                                     ("[", "]", "brackets")):
        if content.count(open_ch) != content.count(close_ch):
            return ValidationResult(False, f"unbalanced {label} in {path}")

    # The app component must still export a default.
    if path.lower().endswith(("app.jsx", "app.tsx", "app.js", "app.ts")):
        if "export default" not in content:
            return ValidationResult(False, f"{path} has no default export")

    # Only React may be imported; the scaffold provides nothing else.
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") and " from " in stripped:
            source = stripped.split(" from ", 1)[1].strip().strip(";'\"")
            if not (source == "react" or source.startswith("react")
                    or source.startswith(".") or source.startswith("/")):
                return ValidationResult(False, f"{path} imports a disallowed package: {source}")

    return ValidationResult(True)


def _validate_css(path: str, content: str) -> ValidationResult:
    if content.count("{") != content.count("}"):
        return ValidationResult(False, f"unbalanced braces in {path}")
    return ValidationResult(True)


def validate_all(files: dict[str, str]) -> ValidationResult:
    """Validate a mapping of path -> content. Returns the first failure."""
    for path, content in files.items():
        result = validate_file(path, content)
        if not result.ok:
            return result
    return ValidationResult(True)


def validate_workspace(workspace: Path, changed: list[str] | None = None) -> ValidationResult:
    """Confirm the workspace still looks like an intact project after an edit.

    This replaces the old runtime liveness check: there is no dev server to poll
    anymore, so "the edit succeeded" is redefined as "the workspace is still a
    well-formed project on disk" rather than "a running app answered HTTP".
    Each edited file's *content* is already statically validated by
    ``validate_file`` before it is written (see ``builder/patcher.py``) — this
    only checks the workspace shape itself wasn't left broken by the write.

    Intentionally shallow, per the same philosophy as ``validate_file``: catch
    the ways an edit can leave the project unusable without becoming a build
    system in its own right.
    """
    if not workspace.exists() or not workspace.is_dir():
        return ValidationResult(False, f"workspace does not exist: {workspace}")
    if not (workspace / "package.json").exists():
        return ValidationResult(False, "package.json is missing from the workspace")
    if not (workspace / "src").is_dir():
        return ValidationResult(False, "src/ directory is missing from the workspace")
    for rel in changed or []:
        if not (workspace / rel).exists():
            return ValidationResult(False, f"{rel} was not found on disk after the edit")
    return ValidationResult(True)
