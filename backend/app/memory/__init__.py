"""EDEN memory subsystem — durable, provider-independent long-term memory.

The foundation for future capabilities (RAG, project memory, personalization,
autonomous/long-running tasks). Fully isolated: it depends only on config, a
small JSON utility, and the canonical ``LLMProvider.stream_reply`` interface —
never on builder, editor, research, events, or the tool registry, and it emits
no events.

Public surface:
  build_memory_manager()  — construct the manager from config (the entry point)
  MemoryManager           — the facade the conversation pipeline calls
  MemoryType, MemoryRecord, RetrievedMemory — the data model

Modules:
  models      — MemoryType / MemoryRecord / RetrievedMemory / ExtractedMemory
  embeddings  — EmbeddingProvider interface + local / Gemini / OpenAI providers
  storage     — StorageBackend interface + SQLite backend
  retrieval   — weighted semantic + recency + importance ranking
  updater     — the store/update/ignore decision stage
  summarizer  — compaction of long conversations
  manager     — wiring + the two-call facade (retrieve_context, remember_turn)
"""

from __future__ import annotations

from .manager import MemoryManager, build_memory_manager
from .models import ExtractedMemory, MemoryRecord, MemoryType, RetrievedMemory

__all__ = [
    "MemoryManager",
    "build_memory_manager",
    "MemoryType",
    "MemoryRecord",
    "RetrievedMemory",
    "ExtractedMemory",
]
