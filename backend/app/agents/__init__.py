"""EDEN agent subsystem.

Modules:
  intent            — classify user input into typed intents
  task              — central state model for all agent work
  router            — route messages to conversation or agent pipeline
  clarification     — decide whether one clarifying question is needed before a build
  planner           — generate a build plan (new project) from a request
  edit_planner      — generate a minimal edit plan against an existing project
  executor          — perform build I/O (write files, install dependencies)
  orchestrator      — drive the full BUILD workflow end to end
  edit_orchestrator — drive one iterative EDIT of the active project
  narrator          — generate and speak in-character narration at each stage
  researcher        — gather external context for INFORMATION_QUERY requests

  verifier, render_verifier, repairer — dormant; see their module docstrings
  (kept for a possible future live-preview feature, not part of the live path)
"""
