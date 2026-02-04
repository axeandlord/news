"""Source reliability scoring utilities."""

from dataclasses import dataclass


@dataclass
class SourceInfo:
    """Information about a news source."""
    name: str
    reliability: float
    language: str
    category: str


# Default reliability scores if not specified in config
DEFAULT_RELIABILITY = {
    # Tier 1: Highest reliability (0.90-1.0)
    "Reuters": 0.95,
    "CBC": 0.90,
    "Radio-Canada": 0.90,
    "Le Devoir": 0.90,
    "Bloomberg": 0.90,
    "The Economist": 0.95,
    "ArXiv": 1.0,
    "ScienceDaily": 0.95,

    # Tier 2: High reliability (0.80-0.89)
    "CTV": 0.85,
    "Global News": 0.85,
    "Montreal Gazette": 0.85,
    "Al Jazeera": 0.85,
    "BNN": 0.85,

    # Tier 3: Moderate reliability (0.70-0.79)
    "TechCrunch": 0.80,
    "The Verge": 0.80,
    "TVA": 0.80,
    "Journal de Montreal": 0.75,
}


def get_reliability_score(source_name: str, default: float = 0.75) -> float:
    """
    Get reliability score for a source.

    Higher scores = more trustworthy.
    """
    # Check for partial matches
    name_lower = source_name.lower()
    for key, score in DEFAULT_RELIABILITY.items():
        if key.lower() in name_lower:
            return score
    return default


def calculate_cross_reference_bonus(
    article_title: str,
    all_articles: list,
    threshold: float = 0.7
) -> float:
    """
    Calculate bonus for articles reported by multiple sources.

    Returns bonus value (0.0 to 0.3) based on how many sources report similar story.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    if len(all_articles) < 2:
        return 0.0

    # Get all titles
    titles = [article_title] + [a.get("title", "") for a in all_articles if a.get("title") != article_title]

    if len(titles) < 2:
        return 0.0

    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)
        tfidf_matrix = vectorizer.fit_transform(titles)

        # Compare first title (our article) against all others
        similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

        # Count how many are similar enough
        similar_count = np.sum(similarities >= threshold)

        # Bonus scales with number of corroborating sources (max 0.3)
        if similar_count >= 3:
            return 0.30
        elif similar_count >= 2:
            return 0.20
        elif similar_count >= 1:
            return 0.15
        return 0.0
    except Exception:
        return 0.0


def flag_low_reliability(reliability: float, threshold: float = 0.75) -> bool:
    """Check if source should be flagged as lower reliability."""
    return reliability < threshold
