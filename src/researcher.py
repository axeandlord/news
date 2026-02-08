"""Tavily-powered web research for enriching news articles.

Generates research queries from article clusters, executes via Tavily API,
caches results to avoid redundant queries, and deduplicates.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from .curator import CuratedArticle


@dataclass
class ResearchResult:
    """A single research result from Tavily."""
    title: str
    url: str
    content: str
    score: float = 0.0
    query: str = ""


# Ollama for query generation
OLLAMA_API_URL = "http://localhost:11434/api/chat"
LOCAL_MODEL = "qwen2.5:14b"
TAVILY_API_URL = "https://api.tavily.com/search"

# Cache TTL
CACHE_TTL_HOURS = 12


class NewsResearcher:
    """Web research module using Tavily API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TAVILY_API")
        if not self.api_key:
            try:
                self.api_key = subprocess.check_output(
                    ["vault-export", "--get", "tavily_api"], text=True, timeout=5
                ).strip() or None
            except Exception:
                self.api_key = None

        self.ollama_available = self._check_ollama()

    def _check_ollama(self) -> bool:
        try:
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        return bool(self.api_key)

    def research_articles(
        self,
        articles: list[CuratedArticle],
        max_queries: int = 8,
    ) -> list[ResearchResult]:
        """Research top articles with background context.

        Generates smart queries from article clusters, executes via Tavily,
        returns deduplicated results.
        """
        if not self.api_key:
            print("  [WARN] No Tavily API key, skipping research")
            return []

        # Generate research queries from articles
        queries = self._generate_queries_ollama(articles, "background")
        queries = queries[:max_queries]

        if not queries:
            print("  [WARN] No research queries generated")
            return []

        print(f"  Researching with {len(queries)} queries...")
        all_results = []
        for query in queries:
            # Check cache first
            cached = self._get_cached(query)
            if cached:
                all_results.extend(cached)
                continue

            results = self._search_tavily(query, depth="basic")
            if results:
                all_results.extend(results)
                self._cache_results(query, results)

        deduped = self._deduplicate(all_results)
        print(f"  Got {len(deduped)} unique research results")
        return deduped

    def research_topic_deep(
        self,
        articles: list[CuratedArticle],
        category: str,
        analysis_lens: str,
        max_queries: int = 6,
    ) -> list[ResearchResult]:
        """Deep research for a specific topic/category.

        Uses advanced Tavily depth and more targeted queries.
        """
        if not self.api_key:
            return []

        queries = self._generate_deep_queries_ollama(
            articles, category, analysis_lens
        )
        queries = queries[:max_queries]

        if not queries:
            return []

        print(f"  Deep researching {category} with {len(queries)} queries...")
        all_results = []
        for query in queries:
            cached = self._get_cached(query)
            if cached:
                all_results.extend(cached)
                continue

            results = self._search_tavily(query, depth="advanced")
            if results:
                all_results.extend(results)
                self._cache_results(query, results)

        deduped = self._deduplicate(all_results)
        print(f"  Got {len(deduped)} deep research results for {category}")
        return deduped

    def _generate_queries_ollama(
        self, articles: list[CuratedArticle], query_type: str
    ) -> list[str]:
        """Use Ollama to generate smart search queries from articles."""
        if not self.ollama_available:
            # Fallback: extract key phrases from titles
            return self._fallback_queries(articles)

        titles = "\n".join(
            f"- {a.article.title} ({a.article.source})"
            for a in articles[:15]
        )

        prompt = f"""Given these news articles, generate 6-8 search queries to find background context, expert analysis, and data that would help explain WHY these stories matter.

Articles:
{titles}

Generate queries that find:
- Historical context and precedent
- Expert opinions and analyst perspectives
- Relevant data, statistics, market numbers
- Competing viewpoints

Output ONLY the queries, one per line. No numbering, no explanations."""

        result = self._call_ollama(prompt, max_tokens=400, temperature=0.4)
        if not result:
            return self._fallback_queries(articles)

        queries = [
            line.strip().strip("-").strip("•").strip()
            for line in result.strip().split("\n")
            if line.strip() and len(line.strip()) > 10
        ]
        return queries[:8]

    def _generate_deep_queries_ollama(
        self,
        articles: list[CuratedArticle],
        category: str,
        analysis_lens: str,
    ) -> list[str]:
        """Generate targeted deep-dive research queries."""
        if not self.ollama_available:
            return self._fallback_queries(articles)

        titles = "\n".join(
            f"- {a.article.title} ({a.article.source})"
            for a in articles[:10]
        )

        prompt = f"""You are preparing a deep analytical report on {category}. Generate 5-8 specific search queries to find expert analysis, data, and competing viewpoints.

Today's stories in this area:
{titles}

Analysis focus:
{analysis_lens}

Generate queries that find:
- Analyst reports and expert commentary
- Specific data points, market numbers, statistics
- Historical parallels and precedent
- Competing perspectives and counterarguments
- Implications and second-order effects

Output ONLY the queries, one per line. No numbering, no explanations."""

        result = self._call_ollama(prompt, max_tokens=400, temperature=0.4)
        if not result:
            return self._fallback_queries(articles)

        queries = [
            line.strip().strip("-").strip("•").strip()
            for line in result.strip().split("\n")
            if line.strip() and len(line.strip()) > 10
        ]
        return queries[:8]

    def _fallback_queries(self, articles: list[CuratedArticle]) -> list[str]:
        """Generate simple queries from article titles when Ollama unavailable."""
        queries = []
        for a in articles[:5]:
            # Extract key phrase from title
            title = a.article.title
            if len(title) > 60:
                title = title[:60]
            queries.append(f"{title} analysis")
        return queries

    def _search_tavily(
        self, query: str, depth: str = "basic"
    ) -> list[ResearchResult]:
        """Execute a Tavily search query."""
        try:
            resp = httpx.post(
                TAVILY_API_URL,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": depth,
                    "max_results": 3,
                    "include_answer": False,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"    [WARN] Tavily error {resp.status_code}: {resp.text[:100]}")
                return []

            data = resp.json()
            results = []
            for item in data.get("results", []):
                results.append(ResearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", "")[:1000],
                    score=item.get("score", 0.0),
                    query=query,
                ))
            return results
        except Exception as e:
            print(f"    [WARN] Tavily error: {e}")
            return []

    def _deduplicate(self, results: list[ResearchResult]) -> list[ResearchResult]:
        """Remove duplicate results by URL."""
        seen_urls = set()
        deduped = []
        for r in results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                deduped.append(r)
        return deduped

    def _get_cached(self, query: str) -> list[ResearchResult] | None:
        """Check research cache for recent results."""
        from .database import get_research_cache
        cached = get_research_cache(query, ttl_hours=CACHE_TTL_HOURS)
        if cached is None:
            return None
        return [
            ResearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
                query=query,
            )
            for r in cached
        ]

    def _cache_results(self, query: str, results: list[ResearchResult]):
        """Store results in cache."""
        from .database import set_research_cache
        data = [
            {"title": r.title, "url": r.url, "content": r.content, "score": r.score}
            for r in results
        ]
        set_research_cache(query, data)

    def _call_ollama(
        self, prompt: str, max_tokens: int = 400, temperature: float = 0.4
    ) -> str | None:
        """Call local Ollama API."""
        try:
            resp = httpx.post(
                OLLAMA_API_URL,
                json={
                    "model": LOCAL_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature},
                },
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json()["message"]["content"]
        except Exception:
            pass
        return None


def format_research_context(results: list[ResearchResult], max_items: int = 4) -> str:
    """Format research results for inclusion in AI prompts."""
    if not results:
        return ""

    # Sort by score descending, take top items
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)[:max_items]

    parts = []
    for r in sorted_results:
        content = r.content[:500] if r.content else ""
        parts.append(f"Source: {r.title}\nURL: {r.url}\n{content}")

    return "\n---\n".join(parts)
