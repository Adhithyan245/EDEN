"""Pytest bootstrap for the memory-subsystem test suite.

Ensures ``app`` is importable regardless of how pytest is invoked, and keeps
every test isolated: tests only ever use pytest's ``tmp_path`` for SQLite
files, so the production memory store (``backend/eden_memory.db``) is never
opened or touched.
"""

from __future__ import annotations

import os
import sys

# Make the backend package importable (tests/ -> backend/).
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
