"""Select concrete providers from DEMO MODE + credential availability.

This is the one place that knows about vendors. The rest of the app receives an
``LLMProvider`` / ``TTSProvider`` and never asks who's behind it.
"""

from __future__ import annotations

import logging

from ..config import DemoMode, settings
from .base import LLMProvider, TTSProvider
from .llm_mock import MockLLM
from .llm_scripted import ScriptedLLM
from .tts_browser import BrowserTTS

log = logging.getLogger("eden.providers")


def build_llm() -> LLMProvider:
    if settings.mode == DemoMode.PRESENTATION:
        log.info("LLM -> ScriptedLLM (PRESENTATION mode)")
        return ScriptedLLM()

    if settings.has_anthropic:
        try:
            from .llm_claude import ClaudeLLM  # lazy import

            log.info("LLM -> ClaudeLLM")
            return ClaudeLLM()
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            log.warning("ClaudeLLM init failed (%s); falling back to MockLLM", exc)
            return MockLLM()

    log.warning("No Anthropic access configured; LLM -> MockLLM")
    return MockLLM()


def build_tts() -> TTSProvider:
    use_elevenlabs = (
        settings.mode != DemoMode.PRESENTATION
        and settings.voice_enabled
        and settings.has_elevenlabs
    )
    if use_elevenlabs:
        try:
            from .tts_elevenlabs import ElevenLabsTTS  # lazy import

            log.info("TTS -> ElevenLabsTTS (premium)")
            return ElevenLabsTTS()
        except Exception as exc:  # noqa: BLE001
            log.warning("ElevenLabsTTS init failed (%s); falling back to BrowserTTS", exc)

    log.info("TTS -> BrowserTTS")
    return BrowserTTS()


def describe() -> dict[str, str]:
    """A one-line summary of what will be used, for logging / the verify script."""
    return {"llm": build_llm().name, "tts": build_tts().name}
