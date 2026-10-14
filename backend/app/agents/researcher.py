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