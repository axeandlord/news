"""RSS feed fetcher with async support and health tracking."""

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser
import yaml
from dateutil import parser as date_parser


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

    except asyncio.TimeoutError:
        print(f"  [WARN] {source_name}: Timeout")
    except Exception as e:
        print(f"  [WARN] {source_name}: {type(e).__name__}: {e}")

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
    return all_articles


def fetch_feeds_sync(config_path: str = "config/feeds.yaml") -> list[Article]:
    """Synchronous wrapper for fetch_all_feeds."""
    return asyncio.run(fetch_all_feeds(config_path))


if __name__ == "__main__":
    articles = fetch_feeds_sync()
    for a in articles[:5]:
        print(f"\n{a.source} ({a.category}): {a.title}")
