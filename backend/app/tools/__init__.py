"""EDEN tool subsystem.

Modules:
  filesystem — create/read directories and files within a workspace
  shell      — run a command or start a background process
  portguard  — kill stale backend processes still holding our port
  base       — shared ToolResult type

  browser  — dormant (open_browser_url has no callers; the build/edit
             pipeline no longer opens a browser)
  registry — dormant (ToolRegistry/REGISTRY are declared but nothing in the
             codebase imports or binds against them; the executor calls
             filesystem/shell functions directly instead)
"""
