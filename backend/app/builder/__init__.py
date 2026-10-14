"""EDEN builder subsystem.

Modules:
  sandbox         — isolated working directories for build tasks
  template        — the fixed React + Vite scaffold
  generator       — merges a Plan with the scaffold into a GeneratedProject
  active_project  — the session's current project (workspace, files, history)
  validator       — static validation for generated/edited source files
  patcher         — applies an edit plan to the workspace, with validation
  rollback        — file snapshot/restore for a single edit
  version_manager — undo/redo timeline across edits

  ports — dormant; see its module docstring (kept for a possible future
  live-preview feature, not part of the live path)
"""
