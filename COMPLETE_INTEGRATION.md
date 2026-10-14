# Complete Integration: Modified Files

This document shows the final state of all modified files after the Research Agent integration.

---

## File 1: `backend/app/agents/researcher.py`

Complete file with the new SearchToolProvider adapter:

```python
"""
EDEN Research Agent
-------------------
Responsible for answering information-heavy questions that require
current or external knowledge. Gathers information, prepares context,
and allows Gemini to produce a high-quality, well-sourced answer.

Integration flow (future):
    intent.py → INFORMATION_QUERY
    router.py → ResearchAgent.research()
    llm_gemini.py → generate response with context
    narrator.py → display_response / voice_response
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..tools.search import SearchResult, SearchTool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """A single retrieved source."""
    title: str
    url: str
    content: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "snippet": self.snippet or self.content[:200],
        }


Confidence = Literal["high", "medium", "low"]


@dataclass
class ResearchResult:
    """Structured output from the ResearchAgent."""
    query: str
    sources: list[Source] = field(default_factory=list)
    summary: str = ""
    context: str = ""
    confidence: Confidence = "low"
    status: str = "ok"

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "summary": self.summary,
            "context": self.context,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Search provider abstraction
# ---------------------------------------------------------------------------

class SearchProvider(ABC):
    """
    Abstract base class for search backends.

    Future implementations:
        - TavilySearchProvider   (app/tools/search_tavily.py)
        - GoogleSearchProvider   (app/tools/search_google.py)
        - SerperSearchProvider   (app/tools/search_serper.py)
        - BingSearchProvider     (app/tools/search_bing.py)
        - InternalKBProvider     (app/tools/search_internal.py)

    Each must implement `search` and return a list of Source objects.
    """

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[Source]:
        """
        Search for information related to the query.

        Args:
            query:       The refined search query string.
            max_results: Maximum number of sources to return.

        Returns:
            A list of Source objects (may be empty).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# SearchTool adapter
# ---------------------------------------------------------------------------

class SearchToolProvider(SearchProvider):
    """
    Adapts SearchTool (app/tools/search.py) to the SearchProvider interface.
    Allows researcher.py to use the unified search layer without coupling
    to concrete providers.
    """

    def __init__(self, search_tool: SearchTool) -> None:
        """
        Args:
            search_tool: The SearchTool instance to wrap.
        """
        self._tool = search_tool

    async def search(self, query: str, max_results: int = 5) -> list[Source]:
        """Use SearchTool to retrieve results and convert to Source objects."""
        response = await self._tool.search(query=query, limit=max_results)

        if response.status not in ("ok",):
            logger.debug("SearchTool returned status=%s", response.status)
            return []

        sources: list[Source] = []
        for result in response.results:
            source = Source(
                title=result.title,
                url=result.url,
                content=result.content or result.snippet or "",
                snippet=result.snippet,
            )
            sources.append(source)

        return sources


# ---------------------------------------------------------------------------
# Query analysis helpers
# ---------------------------------------------------------------------------

def _analyze_query(query: str) -> dict:
    """
    Light-weight analysis of the user query before searching.

    Returns a dict with keys:
        - refined_query:  A search-optimised version of the query.
        - is_time_sensitive: Whether the query asks for recent/current info.
    """
    lower = query.lower()

    time_keywords = {
        "latest", "recent", "current", "today", "this week",
        "this month", "2024", "2025", "just", "now", "news",
        "update", "updates", "happened",
    }
    is_time_sensitive = any(kw in lower for kw in time_keywords)

    # Strip conversational filler for cleaner search
    filler = ("can you", "could you", "please", "tell me", "what are",
              "what is", "find me", "show me", "give me", "i want to know")
    refined = query.strip()
    for phrase in filler:
        refined = refined.lower().replace(phrase, "").strip()

    return {
        "refined_query": refined or query,
        "is_time_sensitive": is_time_sensitive,
    }


def _build_context(sources: list[Source]) -> str:
    """
    Concatenate source content into a single context string for Gemini.
    Keeps individual sections clearly labelled so the LLM can attribute.
    """
    if not sources:
        return ""

    sections: list[str] = []
    for i, src in enumerate(sources, start=1):
        header = f"[Source {i}] {src.title}"
        if src.url:
            header += f" ({src.url})"
        body = src.content.strip()
        sections.append(f"{header}\n{body}")

    return "\n\n---\n\n".join(sections)


def _assess_confidence(sources: list[Source], is_time_sensitive: bool) -> Confidence:
    """
    Heuristic confidence rating based on how many sources were found
    and whether the query needs current data.
    """
    n = len(sources)
    if n == 0:
        return "low"
    if is_time_sensitive and n < 2:
        return "low"
    if n >= 3:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# Research Agent
# ---------------------------------------------------------------------------

class ResearchAgent:
    """
    EDEN Research Agent.

    Orchestrates query analysis, information retrieval via a pluggable
    SearchProvider, and constructs a ResearchResult that the LLM layer
    (llm_gemini.py) can use to generate a grounded, high-quality answer.

    Usage:
        agent = ResearchAgent(search_provider=TavilySearchProvider(...))
        result = await agent.research("Latest AI trends")
        # result.context → pass to Gemini as grounding context
        # result.sources → display on frontend

    If no provider is supplied, the agent returns a structured empty
    result so the rest of the EDEN pipeline continues without crashing.
    """

    def __init__(
        self,
        search_provider: SearchProvider | None = None,
        max_results: int = 5,
    ) -> None:
        """
        Args:
            search_provider: A SearchProvider implementation. If None,
                             the agent operates in no-op / fallback mode.
            max_results:     Maximum sources to retrieve per query.
        """
        self._provider = search_provider
        self._max_results = max_results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def research(
        self,
        query: str,
        context: dict | None = None,
    ) -> ResearchResult:
        """
        Main entry point for the research workflow.

        Args:
            query:   Raw user query (e.g. "Latest AI trends").
            context: Optional extra context from the conversation
                     (e.g. previous turns, user preferences).

        Returns:
            A ResearchResult containing sources, context string, and
            confidence metadata.
        """
        logger.info("Research started: %s", query)

        # --- Fallback: no provider configured ---
        if self._provider is None:
            logger.warning("ResearchAgent: no search provider configured.")
            return ResearchResult(
                query=query,
                status="no_provider",
                confidence="low",
            )

        # --- Query analysis ---
        analysis = _analyze_query(query)
        refined_query = analysis["refined_query"]
        is_time_sensitive = analysis["is_time_sensitive"]

        # --- Information retrieval ---
        sources: list[Source] = []
        try:
            sources = await self._provider.search(
                query=refined_query,
                max_results=self._max_results,
            )
        except TimeoutError:
            logger.error("ResearchAgent: search timed out for query: %s", query)
            return self._fallback_result(query, reason="timeout")
        except Exception as exc:  # noqa: BLE001
            logger.error("ResearchAgent: search failed: %s", exc)
            return self._fallback_result(query, reason="search_error")

        logger.info("Research completed: %s sources", len(sources))

        # --- Source processing ---
        if not sources:
            return ResearchResult(
                query=query,
                status="no_results",
                confidence="low",
            )

        # --- Build context for Gemini ---
        context_text = _build_context(sources)
        confidence = _assess_confidence(sources, is_time_sensitive)

        return ResearchResult(
            query=query,
            sources=sources,
            context=context_text,
            confidence=confidence,
            status="ok",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_result(query: str, reason: str) -> ResearchResult:
        """Return a safe, structured empty result on error."""
        return ResearchResult(
            query=query,
            status=reason,
            confidence="low",
        )
```

**Key addition:** `SearchToolProvider` class (lines 108-141) that adapts SearchTool to the SearchProvider interface.

---

## File 2: `backend/app/config.py`

Key additions in the `Settings` class:

```python
# After line 51 (in __init__):

# Search / Research
self.tavily_api_key = _env("TAVILY_API_KEY")

# After has_elevenlabs property (around line 81):

@property
def has_tavily(self) -> bool:
    """True if Tavily search should be available."""
    return bool(self.tavily_api_key)
```

---

## File 3: `backend/app/providers/factory.py`

Complete file with new builder functions:

```python
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
```

**New functions:** `build_search_tool()` and `build_research_agent()` (lines 63-84)

---

## File 4: `backend/app/main.py`

Key additions and modifications:

### 1. Import the research agent at startup (after line 72):
```python
# Research agent for INFORMATION_QUERY requests.
RESEARCH = factory.build_research_agent()
```

### 2. Add research phase in `_handle_user_message()` (before LLM call):
```python
# ------------------------------------------------------------------
# Research phase (INFORMATION_QUERY only)
# Gather external knowledge before asking the LLM to respond.
# ------------------------------------------------------------------
research_context = ""
if detected_intent is not None and detected_intent.value == "information_query":
    try:
        log.info("Research phase: gathering information for query: %s", text[:80])
        research_result = await RESEARCH.research(text)
        if research_result.status == "ok" and research_result.sources:
            research_context = research_result.context
            log.info(
                "Research completed: %d sources, confidence=%s",
                len(research_result.sources),
                research_result.confidence,
            )
            # Inject research context into the user message
            enriched_content = f"{text}\n\n[Research context:\n{research_context}]"
            llm_messages = session.messages[:-1] + [
                {"role": "user", "content": enriched_content}
            ]
        else:
            log.info("Research yielded no results; proceeding without context")
    except Exception as exc:  # noqa: BLE001
        log.warning("Research failed; proceeding without context: %s", exc)
```

This code block goes between line 336 (where `llm_messages` is set) and line 344 (where `LLM.stream_reply` is called).

---

## File 5: `backend/.env.example`

Added section (after line 27):
```
# ── Research / Search — optional ──
# If unset, INFORMATION_QUERY requests proceed without external knowledge.
# Get your key at https://tavily.com
TAVILY_API_KEY=
```

---

## Summary of Changes

| File | Type | Change |
|------|------|--------|
| `researcher.py` | Added | `SearchToolProvider` class (adapter) |
| `researcher.py` | Added | Import `SearchResult, SearchTool` |
| `config.py` | Added | `tavily_api_key` configuration variable |
| `config.py` | Added | `has_tavily` property |
| `factory.py` | Added | `build_search_tool()` function |
| `factory.py` | Added | `build_research_agent()` function |
| `factory.py` | Added | Imports for research infrastructure |
| `main.py` | Added | `RESEARCH` initialization at startup |
| `main.py` | Added | Research phase in message handler |
| `.env.example` | Added | TAVILY_API_KEY documentation |

**Total lines added:** ~150  
**Files modified:** 5  
**Backward compatible:** ✅ Yes  
**Breaking changes:** ❌ None  

---

## Verification

All changes follow EDEN's design principles:

✅ **Dependency injection:** SearchTool passed to SearchToolProvider, researcher accepts provider  
✅ **Graceful fallback:** Works without Tavily API key  
✅ **Error handling:** Research failures don't crash pipeline  
✅ **Logging:** Progress logged at appropriate levels  
✅ **No breaking changes:** Existing code paths unchanged  
✅ **Separation of concerns:** researcher orchestrates; search retrieves; factory builds  
✅ **Intent-aware:** Only INFORMATION_QUERY triggers research  
✅ **Transparent injection:** Research context added to message, not system prompt  

