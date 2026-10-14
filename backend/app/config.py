"""Runtime configuration for EDEN, including DEMO MODE resolution.

All settings come from the environment (loaded from `backend/.env` when present).
Nothing here is required: with no credentials, EDEN runs on a mock LLM and
browser text-to-speech so development is never blocked on external APIs.
"""

from __future__ import annotations

import os
from enum import Enum

try:
    from dotenv import load_dotenv

    # Load backend/.env regardless of the current working directory.
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_here, ".env"))
except Exception:  # dotenv is optional; env vars still work without it.
    pass


class DemoMode(str, Enum):
    """The three reliability levels EDEN can run in."""

    LIVE = "LIVE"
    SAFE = "SAFE"
    PRESENTATION = "PRESENTATION"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool = False) -> bool:
    return (_env(name, str(default)) or "").strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        mode_raw = (_env("EDEN_MODE", "SAFE") or "SAFE").upper()
        try:
            self.mode = DemoMode(mode_raw)
        except ValueError:
            self.mode = DemoMode.SAFE

        # Reasoning
        self.gemini_api_key = _env("GEMINI_API_KEY")
        self.model_voice = _env("EDEN_MODEL_VOICE", "gemini-3.1-flash-lite")
        self.model_builder = _env("EDEN_MODEL_BUILDER", "gemini-3.1-flash-lite")

        # Search / Research
        self.tavily_api_key = _env("TAVILY_API_KEY")

        # Optional OpenAI key — used only by the memory subsystem's optional
        # OpenAI embedding provider; unset by default.
        self.openai_api_key = _env("OPENAI_API_KEY")

        # Voice
        self.elevenlabs_api_key = _env("ELEVENLABS_API_KEY")
        self.elevenlabs_voice_id = _env("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        self.voice_enabled = _bool("EDEN_VOICE_ENABLED", True)

        # Agent subsystem
        self.agent_enabled = _bool("EDEN_AGENT_ENABLED", False)
        # Build timeout (seconds). npm install on a cold cache can be slow.
        self.build_install_timeout = int(_env("EDEN_BUILD_INSTALL_TIMEOUT", "240") or "240")

        # Memory subsystem — long-term, provider-independent memory.
        # Enabled by default; fully self-contained and degrades to a no-op if
        # anything is unavailable, so it never blocks the conversation pipeline.
        self.memory_enabled = _bool("EDEN_MEMORY_ENABLED", True)
        # SQLite file; persists across restarts. Defaults beside the backend
        # package so long-term memory actually survives (not the temp dir).
        _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.memory_db_path = _env(
            "EDEN_MEMORY_DB_PATH", os.path.join(_backend_dir, "eden_memory.db")
        )
        # Embedding provider: "local" (default, offline, no deps) | "gemini" | "openai".
        self.embedding_provider = _env("EDEN_EMBEDDING_PROVIDER", "local")
        self.memory_embedding_dim = int(_env("EDEN_MEMORY_EMBEDDING_DIM", "256") or "256")
        # Retrieval: how many memories may be injected, the score floor, and the
        # relative weights of the three ranking signals.
        self.memory_max_injected = int(_env("EDEN_MEMORY_MAX_INJECTED", "6") or "6")
        self.memory_min_score = float(_env("EDEN_MEMORY_MIN_SCORE", "0.15") or "0.15")
        self.memory_weight_semantic = float(_env("EDEN_MEMORY_WEIGHT_SEMANTIC", "0.6") or "0.6")
        self.memory_weight_recency = float(_env("EDEN_MEMORY_WEIGHT_RECENCY", "0.2") or "0.2")
        self.memory_weight_importance = float(_env("EDEN_MEMORY_WEIGHT_IMPORTANCE", "0.2") or "0.2")
        self.memory_recency_half_life_days = float(
            _env("EDEN_MEMORY_RECENCY_HALF_LIFE_DAYS", "14") or "14"
        )
        # Summarize the running conversation every N messages.
        self.memory_summary_threshold = int(_env("EDEN_MEMORY_SUMMARY_THRESHOLD", "20") or "20")

        # Misc
        self.user_name = _env("EDEN_USER_NAME", "Adhithyan")
        self.host = _env("EDEN_HOST", "0.0.0.0")
        self.port = int(_env("EDEN_PORT", "8000") or "8000")

    @property
    def has_gemini(self) -> bool:
        """True if a Gemini LLM should be attempted."""
        return bool(self.gemini_api_key)

    @property
    def has_elevenlabs(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def has_tavily(self) -> bool:
        """True if Tavily search should be available."""
        return bool(self.tavily_api_key)


settings = Settings()
