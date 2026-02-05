"""SQLite database for BRIEF learning engine.

Stores user preferences, engagement data, and source health.
Database is isolated to this project in data/brief.db
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Database path - isolated to this project
DB_PATH = Path(__file__).parent.parent / "data" / "brief.db"


def get_db_path() -> Path:
    """Get the database path, ensuring directory exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    """Get a database connection with context management."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_database():
    """Initialize the database schema."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # User preferences - learned interest weights
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                keyword TEXT,
                weight REAL DEFAULT 1.0,
                source TEXT,  -- 'initial', 'click', 'feedback', 'decay'
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, keyword)
            )
        """)

        # Article engagement tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT NOT NULL UNIQUE,
                title TEXT,
                source TEXT,
                category TEXT,
                url TEXT,
                clicked INTEGER DEFAULT 0,
                click_time TIMESTAMP,
                time_spent_seconds INTEGER,
                feedback INTEGER,  -- -1 = dislike, 0 = neutral, 1 = like
                feedback_time TIMESTAMP,
                shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Click history for pattern learning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS click_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT NOT NULL,
                category TEXT,
                keywords TEXT,  -- JSON array of extracted keywords
                clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hour_of_day INTEGER,
                day_of_week INTEGER
            )
        """)

        # Explicit feedback log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT NOT NULL,
                feedback_type TEXT,  -- 'like', 'dislike', 'more_like_this', 'less_like_this'
                category TEXT,
                keywords TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Source health tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL UNIQUE,
                url TEXT,
                last_success TIMESTAMP,
                last_failure TIMESTAMP,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                avg_articles INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Related articles cache (for context linking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT NOT NULL,
                related_hash TEXT NOT NULL,
                relation_type TEXT,  -- 'same_story', 'follow_up', 'related_topic'
                similarity_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(article_hash, related_hash)
            )
        """)

        # Article cache for historical context
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_hash TEXT NOT NULL UNIQUE,
                title TEXT,
                summary TEXT,
                ai_summary TEXT,
                source TEXT,
                category TEXT,
                url TEXT,
                published_at TIMESTAMP,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                keywords TEXT  -- JSON array
            )
        """)

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_engagement_hash ON article_engagement(article_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_engagement_category ON article_engagement(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_click_history_category ON click_history(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_cache_hash ON article_cache(article_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_cache_date ON article_cache(fetched_at)")

        print(f"Database initialized at {get_db_path()}")


def record_article_shown(article_hash: str, title: str, source: str, category: str, url: str):
    """Record that an article was shown to the user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO article_engagement
            (article_hash, title, source, category, url, shown_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (article_hash, title, source, category, url, datetime.now()))


def record_click(article_hash: str, category: str, keywords: list[str] = None):
    """Record that user clicked an article."""
    now = datetime.now()
    keywords_json = str(keywords) if keywords else "[]"

    with get_connection() as conn:
        cursor = conn.cursor()

        # Update engagement record
        cursor.execute("""
            UPDATE article_engagement
            SET clicked = 1, click_time = ?
            WHERE article_hash = ?
        """, (now, article_hash))

        # Add to click history
        cursor.execute("""
            INSERT INTO click_history
            (article_hash, category, keywords, clicked_at, hour_of_day, day_of_week)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (article_hash, category, keywords_json, now, now.hour, now.weekday()))

        # Boost category weight
        _boost_preference(cursor, category, None, 0.05, 'click')


def record_feedback(article_hash: str, feedback_type: str, category: str, keywords: list[str] = None):
    """Record explicit user feedback (like/dislike)."""
    keywords_json = str(keywords) if keywords else "[]"

    with get_connection() as conn:
        cursor = conn.cursor()

        # Map feedback to numeric value
        feedback_value = 1 if feedback_type in ('like', 'more_like_this') else -1

        # Update engagement record
        cursor.execute("""
            UPDATE article_engagement
            SET feedback = ?, feedback_time = ?
            WHERE article_hash = ?
        """, (feedback_value, datetime.now(), article_hash))

        # Log feedback
        cursor.execute("""
            INSERT INTO feedback_log
            (article_hash, feedback_type, category, keywords)
            VALUES (?, ?, ?, ?)
        """, (article_hash, feedback_type, category, keywords_json))

        # Adjust preferences based on feedback
        boost = 0.1 if feedback_value > 0 else -0.1
        _boost_preference(cursor, category, None, boost, 'feedback')

        # Also boost/reduce keyword weights
        if keywords:
            for kw in keywords[:5]:  # Top 5 keywords
                _boost_preference(cursor, category, kw, boost * 0.5, 'feedback')


def _boost_preference(cursor, category: str, keyword: Optional[str], boost: float, source: str):
    """Boost a preference weight."""
    cursor.execute("""
        INSERT INTO user_preferences (category, keyword, weight, source, updated_at)
        VALUES (?, ?, 1.0 + ?, ?, ?)
        ON CONFLICT(category, keyword) DO UPDATE SET
            weight = MIN(3.0, MAX(0.1, weight + ?)),
            source = ?,
            updated_at = ?
    """, (category, keyword, boost, source, datetime.now(), boost, source, datetime.now()))


def get_learned_weights() -> dict:
    """Get learned preference weights for curation."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get category weights
        cursor.execute("""
            SELECT category, AVG(weight) as avg_weight
            FROM user_preferences
            WHERE keyword IS NULL
            GROUP BY category
        """)

        weights = {'categories': {}, 'keywords': {}}
        for row in cursor.fetchall():
            weights['categories'][row['category']] = row['avg_weight']

        # Get keyword weights
        cursor.execute("""
            SELECT keyword, AVG(weight) as avg_weight
            FROM user_preferences
            WHERE keyword IS NOT NULL
            GROUP BY keyword
            ORDER BY avg_weight DESC
            LIMIT 50
        """)

        for row in cursor.fetchall():
            if row['keyword']:
                weights['keywords'][row['keyword']] = row['avg_weight']

        return weights


def decay_old_preferences(days: int = 30, decay_factor: float = 0.95):
    """Decay preferences older than N days to prevent stale weights."""
    cutoff = datetime.now() - timedelta(days=days)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_preferences
            SET weight = MAX(0.5, weight * ?),
                source = 'decay',
                updated_at = ?
            WHERE updated_at < ?
        """, (decay_factor, datetime.now(), cutoff))


def record_source_health(source_name: str, url: str, success: bool, article_count: int = 0):
    """Record source fetch health for monitoring."""
    with get_connection() as conn:
        cursor = conn.cursor()

        if success:
            cursor.execute("""
                INSERT INTO source_health (source_name, url, last_success, success_count, avg_articles)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    last_success = ?,
                    success_count = success_count + 1,
                    avg_articles = (avg_articles + ?) / 2
            """, (source_name, url, datetime.now(), article_count, datetime.now(), article_count))
        else:
            cursor.execute("""
                INSERT INTO source_health (source_name, url, last_failure, failure_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(source_name) DO UPDATE SET
                    last_failure = ?,
                    failure_count = failure_count + 1
            """, (source_name, url, datetime.now(), datetime.now()))


def get_unhealthy_sources(failure_threshold: int = 5) -> list[str]:
    """Get sources that are consistently failing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT source_name
            FROM source_health
            WHERE failure_count > ?
            AND (last_success IS NULL OR last_failure > last_success)
        """, (failure_threshold,))

        return [row['source_name'] for row in cursor.fetchall()]


def cache_article(article_hash: str, title: str, summary: str, ai_summary: str,
                  source: str, category: str, url: str, published_at: datetime,
                  keywords: list[str] = None):
    """Cache article for historical context and relation building."""
    keywords_json = str(keywords) if keywords else "[]"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO article_cache
            (article_hash, title, summary, ai_summary, source, category, url, published_at, keywords)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (article_hash, title, summary, ai_summary, source, category, url, published_at, keywords_json))


def find_related_cached_articles(keywords: list[str], category: str,
                                  days_back: int = 7, limit: int = 5) -> list[dict]:
    """Find related articles from cache for context linking."""
    cutoff = datetime.now() - timedelta(days=days_back)

    with get_connection() as conn:
        cursor = conn.cursor()

        # Simple keyword matching - could be enhanced with embeddings later
        keyword_conditions = " OR ".join(["keywords LIKE ?" for _ in keywords])
        keyword_params = [f"%{kw}%" for kw in keywords]

        cursor.execute(f"""
            SELECT * FROM article_cache
            WHERE (category = ? OR {keyword_conditions})
            AND fetched_at > ?
            ORDER BY fetched_at DESC
            LIMIT ?
        """, [category] + keyword_params + [cutoff, limit])

        return [dict(row) for row in cursor.fetchall()]


def get_engagement_stats() -> dict:
    """Get engagement statistics for analysis."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Overall stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_shown,
                SUM(clicked) as total_clicked,
                SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) as total_likes,
                SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) as total_dislikes
            FROM article_engagement
            WHERE shown_at > datetime('now', '-30 days')
        """)

        overall = dict(cursor.fetchone())

        # Per category
        cursor.execute("""
            SELECT
                category,
                COUNT(*) as shown,
                SUM(clicked) as clicked,
                ROUND(100.0 * SUM(clicked) / COUNT(*), 1) as click_rate
            FROM article_engagement
            WHERE shown_at > datetime('now', '-30 days')
            GROUP BY category
            ORDER BY click_rate DESC
        """)

        by_category = [dict(row) for row in cursor.fetchall()]

        return {
            'overall': overall,
            'by_category': by_category
        }


# Initialize on import
init_database()


if __name__ == "__main__":
    # Test the database
    init_database()
    print(f"Database at: {get_db_path()}")
    print(f"Exists: {get_db_path().exists()}")

    # Test recording
    record_article_shown("test123", "Test Article", "Test Source", "tech_ai", "http://example.com")
    record_click("test123", "tech_ai", ["AI", "machine learning"])
    record_feedback("test123", "like", "tech_ai", ["AI"])

    # Test retrieval
    weights = get_learned_weights()
    print(f"Learned weights: {weights}")

    stats = get_engagement_stats()
    print(f"Stats: {stats}")
