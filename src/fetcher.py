"""RSS feed fetcher with async support, health tracking, and full article extraction."""

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser
import yaml
from dateutil import parser as date_parser

from .database import record_source_health, get_unhealthy_sources


def generate_article_hash(title: str, link: str) -> str:
    """Generate a unique hash for an article."""
    content = f"{title}:{link}".encode('utf-8')
    return hashlib.md5(content).hexdigest()[:16]


@dataclass
class Article:
    """Normalized article from any RSS feed."""
    title: str
    link: str
    summary: str
    source: str
    published: datetime
    category: str
    language: str
    reliability: float
    article_hash: str = field(default="")
    full_text: str = field(default="")

    def __post_init__(self):
        if not self.article_hash:
            self.article_hash = generate_article_hash(self.title, self.link)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "source": self.source,
            "published": self.published.isoformat(),
            "category": self.category,
            "language": self.language,
            "reliability": self.reliability,
            "article_hash": self.article_hash,
        }


def load_feeds_config(config_path: str = "config/feeds.yaml") -> dict:
    """Load feeds configuration from YAML."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_date(date_str: Optional[str]) -> datetime:
    """Parse date string to datetime, fallback to now if invalid."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


async def fetch_feed(
    session: aiohttp.ClientSession,
    url: str,
    source_name: str,
    category: str,
    language: str,
    reliability: float,
    timeout: int = 30,
    max_articles: int = 20,
) -> list[Article]:
    """Fetch and parse a single RSS feed."""
    articles = []

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                print(f"  [WARN] {source_name}: HTTP {resp.status}")
                record_source_health(source_name, url, success=False)
                return []

            content = await resp.text()
            feed = feedparser.parse(content)

            for entry in feed.entries[:max_articles]:
                # Extract summary, preferring content over summary
                summary = ""
                if hasattr(entry, "content") and entry.content:
                    summary = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    summary = entry.summary or ""
                elif hasattr(entry, "description"):
                    summary = entry.description or ""

                # Clean HTML from summary
                from bs4 import BeautifulSoup
                summary = BeautifulSoup(summary, "html.parser").get_text()[:500]

                # Parse publication date
                pub_date = None
                for date_field in ["published", "updated", "created"]:
                    if hasattr(entry, date_field):
                        pub_date = getattr(entry, date_field)
                        break

                articles.append(Article(
                    title=entry.get("title", "No title"),
                    link=entry.get("link", ""),
                    summary=summary.strip(),
                    source=source_name,
                    published=parse_date(pub_date),
                    category=category,
                    language=language,
                    reliability=reliability,
                ))

            print(f"  [OK] {source_name}: {len(articles)} articles")
            record_source_health(source_name, url, success=True, article_count=len(articles))

    except asyncio.TimeoutError:
        print(f"  [WARN] {source_name}: Timeout")
        record_source_health(source_name, url, success=False)
    except Exception as e:
        print(f"  [WARN] {source_name}: {type(e).__name__}: {e}")
        record_source_health(source_name, url, success=False)

    return articles


async def fetch_all_feeds(config_path: str = "config/feeds.yaml") -> list[Article]:
    """Fetch all feeds from configuration."""
    config = load_feeds_config(config_path)
    sources = config.get("sources", {})
    fetch_config = config.get("fetch", {})

    timeout = fetch_config.get("timeout", 30)
    max_articles = fetch_config.get("max_articles_per_feed", 20)
    user_agent = fetch_config.get("user_agent", "NewsAggregator/1.0")

    all_articles = []

    headers = {"User-Agent": user_agent}
    connector = aiohttp.TCPConnector(limit=10, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = []

        for category, feeds in sources.items():
            for feed in feeds:
                tasks.append(fetch_feed(
                    session=session,
                    url=feed["url"],
                    source_name=feed["name"],
                    category=category,
                    language=feed.get("language", "en"),
                    reliability=feed.get("reliability", 0.75),
                    timeout=timeout,
                    max_articles=max_articles,
                ))

        print(f"Fetching {len(tasks)} feeds...")
        results = await asyncio.gather(*tasks)

        for articles in results:
            all_articles.extend(articles)

    # Sort by date, newest first
    all_articles.sort(key=lambda a: a.published, reverse=True)

    print(f"Total: {len(all_articles)} articles")

    # Report unhealthy sources
    unhealthy = get_unhealthy_sources()
    if unhealthy:
        print(f"  Unhealthy sources ({len(unhealthy)}): {', '.join(unhealthy)}")

    # Extract full article text for top articles
    print("Extracting full article text...")
    all_articles = await extract_full_texts(all_articles, max_articles=80)

    return all_articles


async def extract_full_texts(
    articles: list[Article],
    max_articles: int = 80,
) -> list[Article]:
    """Extract full article text using trafilatura for top articles."""
    try:
        import trafilatura
    except ImportError:
        print("  [WARN] trafilatura not installed, using RSS summaries only")
        return articles

    # Only extract for top N articles (sorted by date already)
    to_extract = articles[:max_articles]
    skipped = articles[max_articles:]

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=10)

    def _extract_one(article: Article) -> Article:
        """Extract full text for a single article."""
        if not article.link:
            return article

        # Reddit posts: use RSS summary as full_text (trafilatura can't extract reddit)
        if 'reddit.com' in article.link:
            if article.summary and len(article.summary) > 100:
                article.full_text = article.summary[:3000]
            return article

        try:
            downloaded = trafilatura.fetch_url(article.link)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=True,
                )
                if text and len(text) > 100:
                    article.full_text = text[:3000]  # Cap at 3000 chars
        except Exception:
            pass  # Silently fall back to RSS summary

        # Fallback: newspaper4k if trafilatura didn't get text
        if not article.full_text:
            try:
                from newspaper import Article as NewsArticle
                news_article = NewsArticle(article.link)
                news_article.download()
                news_article.parse()
                if news_article.text and len(news_article.text) > 100:
                    article.full_text = news_article.text[:3000]
            except Exception:
                pass

        return article

    # Run extractions concurrently in thread pool
    tasks = [loop.run_in_executor(executor, _extract_one, a) for a in to_extract]
    extracted = await asyncio.gather(*tasks)

    extracted_count = sum(1 for a in extracted if a.full_text)
    print(f"  Extracted full text for {extracted_count}/{len(to_extract)} articles")

    return list(extracted) + skipped


def fetch_feeds_sync(config_path: str = "config/feeds.yaml") -> list[Article]:
    """Synchronous wrapper for fetch_all_feeds."""
    return asyncio.run(fetch_all_feeds(config_path))


if __name__ == "__main__":
    articles = fetch_feeds_sync()
    for a in articles[:5]:
        print(f"\n{a.source} ({a.category}): {a.title}")
