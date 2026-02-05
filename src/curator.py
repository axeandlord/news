"""AI-powered news curation and scoring with learning integration."""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .fetcher import Article
from .database import (
    get_learned_weights,
    record_article_shown,
    cache_article,
    decay_old_preferences,
)


@dataclass
class CuratedArticle:
    """Article with curation score and AI summary."""
    article: Article
    score: float
    ai_summary: str = ""
    why_it_matters: str = ""

    def to_dict(self) -> dict:
        d = self.article.to_dict()
        d["score"] = self.score
        d["ai_summary"] = self.ai_summary
        d["why_it_matters"] = self.why_it_matters
        return d


def load_curation_config(config_path: str = "config/curation.yaml") -> dict:
    """Load curation rules from YAML."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def calculate_base_score(
    article: Article,
    config: dict,
    learned_weights: dict | None = None
) -> float:
    """
    Calculate base relevance score for an article.

    Integrates learned weights from user behavior.
    """
    score = 0.5  # Start at neutral

    interests = config.get("user_interests", {})

    # Get base category weight from config
    category_weights = interests.get("categories", {})
    category_weight = category_weights.get(article.category, 1.0)

    # Apply learned category adjustment
    if learned_weights:
        learned_cat = learned_weights.get("categories", {})
        if article.category in learned_cat:
            # Learned weight is a multiplier (0.1 to 3.0)
            learned_mult = learned_cat[article.category]
            category_weight *= learned_mult

    score *= category_weight

    # Keyword matching (static from config)
    keywords = interests.get("keywords", {})
    text = f"{article.title} {article.summary}".lower()

    for kw in keywords.get("high_priority", []):
        if kw.lower() in text:
            score += 0.3
            break

    for kw in keywords.get("medium_priority", []):
        if kw.lower() in text:
            score += 0.2
            break

    for kw in keywords.get("low_priority", []):
        if kw.lower() in text:
            score += 0.1
            break

    # Apply learned keyword boosts
    if learned_weights:
        learned_kw = learned_weights.get("keywords", {})
        for kw, weight in learned_kw.items():
            if kw.lower() in text:
                # Learned keyword boost (scaled down)
                score += (weight - 1.0) * 0.1

    # Reliability factor
    scoring = config.get("scoring", {})
    reliability_weight = scoring.get("reliability_weight", 0.25)
    score += article.reliability * reliability_weight

    # High reliability bonus
    if article.reliability >= 0.9:
        score += scoring.get("high_reliability_bonus", 0.1)

    # Recency bonus (articles from last 6 hours get boost)
    now = datetime.now(timezone.utc)
    age = now - article.published
    if age < timedelta(hours=6):
        score += 0.1
    elif age < timedelta(hours=12):
        score += 0.05

    return min(score, 2.0)  # Cap at 2.0


def deduplicate_articles(
    articles: list[Article],
    threshold: float = 0.7
) -> list[Article]:
    """Remove duplicate/similar articles, keeping higher reliability source."""
    if len(articles) < 2:
        return articles

    titles = [a.title for a in articles]

    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)
        tfidf_matrix = vectorizer.fit_transform(titles)
        similarity_matrix = cosine_similarity(tfidf_matrix)

        # Track which articles to keep
        keep = [True] * len(articles)

        for i in range(len(articles)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(articles)):
                if not keep[j]:
                    continue
                if similarity_matrix[i, j] >= threshold:
                    # Keep the one with higher reliability
                    if articles[i].reliability >= articles[j].reliability:
                        keep[j] = False
                    else:
                        keep[i] = False
                        break

        return [a for a, k in zip(articles, keep) if k]
    except Exception:
        return articles


def generate_ai_summary(
    articles: list[CuratedArticle],
    config: dict
) -> list[CuratedArticle]:
    """Generate AI summaries using OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("  [WARN] No OPENROUTER_API_KEY, skipping AI summaries")
        return articles

    summary_config = config.get("summaries", {})
    include_why = summary_config.get("include_why_it_matters", True)

    # Summarize more articles for BRIEF v2 (top 20)
    top_articles = articles[:20]

    print(f"Generating AI summaries for {len(top_articles)} articles...")

    for curated in top_articles:
        article = curated.article

        prompt = f"""Summarize this news article in 2-3 sentences. Be factual and concise.

Title: {article.title}
Source: {article.source}
Content: {article.summary[:1000]}

Respond in this exact format:
SUMMARY: [your summary]
{"WHY IT MATTERS: [one sentence on broader significance]" if include_why else ""}"""

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "https://news.bezman.ca",
                    },
                    json={
                        "model": "anthropic/claude-3-haiku",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                    },
                )

                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]

                    # Parse response
                    summary_match = re.search(r"SUMMARY:\s*(.+?)(?=WHY IT MATTERS:|$)", content, re.DOTALL)
                    why_match = re.search(r"WHY IT MATTERS:\s*(.+)", content, re.DOTALL)

                    if summary_match:
                        curated.ai_summary = summary_match.group(1).strip()
                    if why_match:
                        curated.why_it_matters = why_match.group(1).strip()
                else:
                    print(f"  [WARN] API error: {resp.status_code}")

        except Exception as e:
            print(f"  [WARN] Summary failed: {e}")

    return articles


def curate_articles(
    articles: list[Article],
    config_path: str = "config/curation.yaml"
) -> dict[str, list[CuratedArticle]]:
    """
    Score, deduplicate, and organize articles into sections.

    BRIEF v2: Uses learned weights and targets ~50 articles.

    Returns dict with section names as keys.
    """
    config = load_curation_config(config_path)
    scoring_config = config.get("scoring", {})
    brief_config = config.get("daily_brief", {})
    dedup_config = config.get("dedup", {})

    min_score = scoring_config.get("min_score", 0.25)
    similarity_threshold = dedup_config.get("similarity_threshold", 0.7)

    # Get learned weights from database
    print("Loading learned preferences...")
    learned_weights = get_learned_weights()
    cat_count = len(learned_weights.get("categories", {}))
    kw_count = len(learned_weights.get("keywords", {}))
    if cat_count or kw_count:
        print(f"  Found {cat_count} category weights, {kw_count} keyword weights")
    else:
        print("  No learned weights yet (new user)")

    # Decay old preferences periodically
    learning_config = config.get("learning", {})
    decay_days = learning_config.get("decay_after_days", 30)
    decay_factor = learning_config.get("decay_factor", 0.95)
    decay_old_preferences(days=decay_days, decay_factor=decay_factor)

    print("Deduplicating articles...")
    articles = deduplicate_articles(articles, similarity_threshold)
    print(f"  {len(articles)} unique articles")

    # Score all articles with learned weights
    print("Scoring articles...")
    scored = []
    for article in articles:
        score = calculate_base_score(article, config, learned_weights)
        if score >= min_score:
            scored.append(CuratedArticle(article=article, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    print(f"  {len(scored)} articles above threshold")

    # Generate AI summaries for top articles
    scored = generate_ai_summary(scored, config)

    # Organize into sections based on BRIEF v2 targets
    sections = {}
    used_links = set()  # Avoid same article in multiple sections

    for section in brief_config.get("sections", []):
        name = section["name"]
        count = section.get("count", 5)
        category = section.get("category")

        section_articles = []

        # First pass: exact category match
        for curated in scored:
            if curated.article.link in used_links:
                continue

            if category and curated.article.category != category:
                continue

            section_articles.append(curated)
            used_links.add(curated.article.link)

            if len(section_articles) >= count:
                break

        sections[name] = section_articles

    # Track articles shown (for learning engine)
    total_shown = 0
    for section_name, items in sections.items():
        for item in items:
            record_article_shown(
                article_hash=item.article.article_hash,
                title=item.article.title,
                source=item.article.source,
                category=item.article.category,
                url=item.article.link,
            )
            # Cache article for context
            cache_article(
                article_hash=item.article.article_hash,
                title=item.article.title,
                summary=item.article.summary,
                ai_summary=item.ai_summary,
                source=item.article.source,
                category=item.article.category,
                url=item.article.link,
                published_at=item.article.published,
            )
            total_shown += 1

    print(f"  Tracked {total_shown} articles for learning")

    return sections


if __name__ == "__main__":
    from .fetcher import fetch_feeds_sync

    articles = fetch_feeds_sync()
    sections = curate_articles(articles)

    for name, items in sections.items():
        print(f"\n=== {name} ({len(items)}) ===")
        for c in items:
            print(f"  [{c.score:.2f}] {c.article.title}")
