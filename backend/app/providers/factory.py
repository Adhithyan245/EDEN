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

# ----

from ..agents.researcher import ResearchAgent, SearchToolProvider
from ..tools.search import SearchTool


def build_llm() -> LLMProvider:
    if settings.mode == DemoMode.PRESENTATION:
        log.info("LLM -> ScriptedLLM (PRESENTATION mode)")
        return ScriptedLLM()

    if settings.has_gemini:
        try:
            from .llm_gemini import GeminiLLM  # lazy import

            log.info("LLM -> GeminiLLM")
            return GeminiLLM()
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            log.warning("GeminiLLM init failed (%s); falling back to MockLLM", exc)
            return MockLLM()

    log.warning("No Gemini access configured; LLM -> MockLLM")
    return MockLLM()


def build_tts() -> TTSProvider:
    server_voice = settings.mode != DemoMode.PRESENTATION and settings.voice_enabled
    choice = settings.tts_provider
    if server_voice and choice in ("auto", "gemini") and settings.has_gemini:
        try:
            from .tts_gemini import GeminiTTS  # lazy import

            tts = GeminiTTS()
            if settings.has_elevenlabs:
                from .tts_elevenlabs import ElevenLabsTTS  # lazy import

                tts.fallback = ElevenLabsTTS()
            log.info("TTS -> GeminiTTS (streaming, voice=%s, fallback=%s)", settings.tts_voice,
                     tts.fallback.name if tts.fallback else "browser")
            return tts
        except Exception as exc:  # noqa: BLE001
            log.warning("GeminiTTS init failed (%s); trying the next voice", exc)

    use_elevenlabs = server_voice and choice in ("auto", "elevenlabs") and settings.has_elevenlabs
    if use_elevenlabs:
        try:
            from .tts_elevenlabs import ElevenLabsTTS  # lazy import

            log.info("TTS -> ElevenLabsTTS (premium)")
            return ElevenLabsTTS()
        except Exception as exc:  # noqa: BLE001
            log.warning("ElevenLabsTTS init failed (%s); falling back to BrowserTTS", exc)

    log.info("TTS -> BrowserTTS")
    return BrowserTTS()


def build_search_tool() -> SearchTool:
    """Build a SearchTool with available providers.

    Checks credentials at startup:
        1. TAVILY_API_KEY → TavilySearchProvider
        Returns a no-op SearchTool if no keys are found.
    """
    if settings.has_tavily:
        log.info("SearchTool -> TavilySearchProvider")
        from ..tools.search import TavilySearchProvider
        return SearchTool(provider=TavilySearchProvider(api_key=settings.tavily_api_key))

    log.warning("No search provider configured (set TAVILY_API_KEY)")
    return SearchTool(provider=None)


def build_research_agent() -> ResearchAgent:
    """Build a ResearchAgent with a configured SearchTool."""
    search_tool = build_search_tool()
    provider = SearchToolProvider(search_tool)
    log.info("ResearchAgent initialized with SearchToolProvider")
    return ResearchAgent(search_provider=provider, max_results=5)


def describe() -> dict[str, str]:
    """A one-line summary of what will be used, for logging / the verify script."""
    return {"llm": build_llm().name, "tts": build_tts().name}
