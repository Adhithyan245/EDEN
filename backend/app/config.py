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
        self.anthropic_api_key = _env("ANTHROPIC_API_KEY")
        self.assume_anthropic = _bool("EDEN_ASSUME_ANTHROPIC", False)
        self.model_voice = _env("EDEN_MODEL_VOICE", "claude-sonnet-5")
        self.model_builder = _env("EDEN_MODEL_BUILDER", "claude-opus-4-8")

        # Voice
        self.elevenlabs_api_key = _env("ELEVENLABS_API_KEY")
        self.elevenlabs_voice_id = _env("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        self.voice_enabled = _bool("EDEN_VOICE_ENABLED", True)

        # Misc
        self.user_name = _env("EDEN_USER_NAME", "Adhithyan")
        self.host = _env("EDEN_HOST", "0.0.0.0")
        self.port = int(_env("EDEN_PORT", "8000") or "8000")

    @property
    def has_anthropic(self) -> bool:
        """True if a Claude LLM should be attempted (explicit key or a forced `ant` profile)."""
        return bool(self.anthropic_api_key) or self.assume_anthropic

    @property
    def has_elevenlabs(self) -> bool:
        return bool(self.elevenlabs_api_key)


settings = Settings()
