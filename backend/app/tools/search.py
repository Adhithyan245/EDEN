"""
EDEN Search Tool Layer
----------------------
Provides pluggable information retrieval for the Research Agent.

Environment variables:
    TAVILY_API_KEY   — enables the TavilySearchProvider automatically.

Integration flow (future):
    researcher.py → SearchTool.search() → SearchProvider impl → results
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single normalised search result."""
    title: str
    url: str
    snippet: str
    content: str | None = None
    score: float | None = None          # relevance score when provided by provider

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "content": self.content,
            "score": self.score,
        }


@dataclass
class SearchResponse:
    """Structured response returned by SearchTool."""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    status: str = "ok"          # ok | unavailable | error | empty
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "status": self.status,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Search provider abstraction
# ---------------------------------------------------------------------------

class SearchProvider(ABC):
    """
    Abstract base class for all search backends.

    Subclass this to add a new provider:

        class MyProvider(SearchProvider):
            async def search(self, query, limit=5):
                ...

    Then inject it:

        tool = SearchTool(provider=MyProvider(...))
    """

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """
        Retrieve results for the given query.

        Args:
            query:  The refined search query string.
            limit:  Maximum number of results to return.

        Returns:
            A list of SearchResult objects (may be empty).

        Raises:
            Should NOT raise — return [] on failure and log the error.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tavily provider
# ---------------------------------------------------------------------------

class TavilySearchProvider(SearchProvider):
    """
    Search provider backed by the Tavily API.

    Requires:
        pip install tavily-python

    Environment:
        TAVILY_API_KEY  — must be set for this provider to work.

    Search depth:
        "basic"    — fast, fewer tokens, good for most queries.
        "advanced" — deeper crawl, more content, slower.
    """

    def __init__(
        self,
        api_key: str,
        search_depth: str = "basic",
        include_answer: bool = False,
    ) -> None:
        self._api_key = api_key
        self._search_depth = search_depth
        self._include_answer = include_answer
        self._client: Any = None  # lazy-initialised

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from tavily import TavilyClient  # type: ignore[import]
                self._client = TavilyClient(api_key=self._api_key)
            except ImportError as exc:
                raise RuntimeError(
                    "tavily-python is not installed. "
                    "Run: pip install tavily-python"
                ) from exc
        return self._client

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Call Tavily synchronously inside an async wrapper."""
        import asyncio

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: self._get_client().search(
                    query=query,
                    search_depth=self._search_depth,
                    include_answer=self._include_answer,
                    max_results=limit,
                ),
            )
        except Exception as exc:
            logger.error("TavilySearchProvider: request failed: %s", exc)
            return []

        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", "")[:300],
                content=item.get("content", ""),
                score=item.get("score"),
            )
            for item in raw.get("results", [])
        ]


# ---------------------------------------------------------------------------
# Search Tool — main public interface
# ---------------------------------------------------------------------------

class SearchTool:
    """
    EDEN's information retrieval interface.

    Wraps any SearchProvider with validation, normalisation, error
    handling, and logging so the Research Agent (researcher.py) gets
    a clean, reliable result regardless of which backend is in use.

    Usage:
        # With a provider
        tool = SearchTool(provider=TavilySearchProvider(api_key="..."))
        response = await tool.search("latest AI trends")

        # Without a provider (graceful no-op)
        tool = SearchTool()
        response = await tool.search("latest AI trends")
        # response.status == "unavailable"

    Factory helper:
        tool = SearchTool.from_environment()
        # Automatically enables Tavily if TAVILY_API_KEY is set.
    """

    _MAX_QUERY_LENGTH = 500

    def __init__(self, provider: SearchProvider | None = None) -> None:
        """
        Args:
            provider: A SearchProvider implementation. Pass None to run
                      in graceful no-op mode (returns empty results).
        """
        self._provider = provider

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_environment(cls) -> "SearchTool":
        """
        Build a SearchTool by reading environment variables.

        Checks (in priority order):
            1. TAVILY_API_KEY  → TavilySearchProvider

        Returns a no-op SearchTool if no keys are found.
        """
        tavily_key = os.getenv("TAVILY_API_KEY")
        if tavily_key:
            logger.info("SearchTool: Tavily provider enabled.")
            return cls(provider=TavilySearchProvider(api_key=tavily_key))

        logger.warning(
            "SearchTool: no search provider configured. "
            "Set TAVILY_API_KEY (or another provider key) to enable search."
        )
        return cls(provider=None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> SearchResponse:
        """
        Search for information related to the query.

        Args:
            query: The search query (raw or pre-refined).
            limit: Maximum number of results to return.

        Returns:
            A SearchResponse with status, results list, and the
            original query. Never raises.
        """
        # --- Validate ---
        query = query.strip()
        if not query:
            return SearchResponse(
                query=query,
                status="error",
                message="Query must not be empty.",
            )
        if len(query) > self._MAX_QUERY_LENGTH:
            query = query[: self._MAX_QUERY_LENGTH]
            logger.warning("SearchTool: query truncated to %d chars.", self._MAX_QUERY_LENGTH)

        logger.info("Search started: %s", query)

        # --- No provider ---
        if self._provider is None:
            return SearchResponse(
                query=query,
                status="unavailable",
                message="No search provider is configured.",
            )

        # --- Retrieve ---
        try:
            raw_results = await self._provider.search(query=query, limit=limit)
        except TimeoutError:
            logger.error("SearchTool: provider timed out for query: %s", query)
            return SearchResponse(
                query=query,
                status="error",
                message="Search timed out. Please try again.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("SearchTool: provider raised an unexpected error: %s", exc)
            return SearchResponse(
                query=query,
                status="error",
                message="Search unavailable.",
            )

        # --- Normalise ---
        results = self._normalise(raw_results)

        logger.info("Search completed: %s results", len(results))

        if not results:
            return SearchResponse(
                query=query,
                status="empty",
                message="No results found.",
                results=[],
            )

        return SearchResponse(query=query, results=results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(results: list[SearchResult]) -> list[SearchResult]:
        """
        Clean and validate results from any provider.

        Removes entries with missing titles or URLs, and trims
        unexpectedly long content to keep payloads manageable.
        """
        MAX_CONTENT = 4_000  # characters

        cleaned: list[SearchResult] = []
        for r in results:
            if not r.title or not r.url:
                continue
            if r.content and len(r.content) > MAX_CONTENT:
                r.content = r.content[:MAX_CONTENT]
            if not r.snippet and r.content:
                r.snippet = r.content[:300]
            cleaned.append(r)
        return cleaned