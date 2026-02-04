"""HTML generator for news brief."""

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from .curator import CuratedArticle

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="3600">
    <title>News Brief | news.bezman.ca</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #1a1a1f;
            color: #e8e6e3;
            min-height: 100vh;
            line-height: 1.6;
        }

        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1rem;
        }

        header {
            text-align: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid #3a3a40;
        }

        h1 {
            font-size: 2rem;
            color: #9a8a9f;
            margin-bottom: 0.5rem;
        }

        .updated {
            color: #707070;
            font-size: 0.875rem;
        }

        .audio-player {
            background: #242429;
            border: 1px solid #3a3a40;
            border-radius: 12px;
            padding: 1rem;
            margin: 1.5rem 0;
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .audio-player audio {
            flex: 1;
            height: 40px;
        }

        .audio-label {
            color: #9a8a9f;
            font-size: 0.875rem;
            white-space: nowrap;
        }

        .section {
            margin: 2rem 0;
        }

        .section-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1rem;
            cursor: pointer;
            user-select: none;
        }

        .section-header h2 {
            font-size: 1.25rem;
            color: #c8c8c8;
        }

        .section-toggle {
            color: #9a8a9f;
            font-size: 0.75rem;
            transition: transform 0.2s;
        }

        .section-header.collapsed .section-toggle {
            transform: rotate(-90deg);
        }

        .section-content {
            display: block;
        }

        .section-content.hidden {
            display: none;
        }

        .article {
            background: #242429;
            border: 1px solid #3a3a40;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            transition: border-color 0.2s;
        }

        .article:hover {
            border-color: #9a8a9f;
        }

        .article-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            margin-bottom: 0.5rem;
        }

        .article-title {
            font-size: 1rem;
            font-weight: 600;
            color: #e8e6e3;
        }

        .article-title a {
            color: inherit;
            text-decoration: none;
        }

        .article-title a:hover {
            color: #9a8a9f;
        }

        .article-meta {
            display: flex;
            gap: 0.75rem;
            font-size: 0.75rem;
            color: #808080;
            flex-shrink: 0;
        }

        .article-source {
            color: #9a8a9f;
        }

        .article-summary {
            color: #b0b0b0;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }

        .article-why {
            color: #a08a70;
            font-size: 0.85rem;
            margin-top: 0.5rem;
            font-style: italic;
        }

        .reliability-badge {
            display: inline-block;
            padding: 0.1rem 0.4rem;
            border-radius: 4px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .reliability-high {
            background: #2d4a3e;
            color: #7dba9f;
        }

        .reliability-medium {
            background: #4a4a2d;
            color: #baba7d;
        }

        .reliability-low {
            background: #4a2d2d;
            color: #ba7d7d;
        }

        footer {
            text-align: center;
            padding: 2rem 0;
            color: #505050;
            font-size: 0.75rem;
            border-top: 1px solid #3a3a40;
            margin-top: 2rem;
        }

        footer a {
            color: #9a8a9f;
            text-decoration: none;
        }

        @media (max-width: 600px) {
            .container {
                padding: 1rem;
            }

            h1 {
                font-size: 1.5rem;
            }

            .article-header {
                flex-direction: column;
                gap: 0.5rem;
            }

            .audio-player {
                flex-direction: column;
                align-items: stretch;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>News Brief</h1>
            <p class="updated">Updated {{ updated }}</p>
        </header>

        {% if audio_file %}
        <div class="audio-player">
            <span class="audio-label">Listen to brief</span>
            <audio controls preload="none">
                <source src="{{ audio_file }}" type="audio/mpeg">
            </audio>
        </div>
        {% endif %}

        {% for section_name, articles in sections.items() %}
        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="section-toggle">&#9660;</span>
                <h2>{{ section_name }}</h2>
            </div>
            <div class="section-content">
                {% for item in articles %}
                <article class="article">
                    <div class="article-header">
                        <h3 class="article-title">
                            <a href="{{ item.article.link }}" target="_blank" rel="noopener">
                                {{ item.article.title }}
                            </a>
                        </h3>
                        <div class="article-meta">
                            <span class="article-source">{{ item.article.source }}</span>
                            <span class="reliability-badge reliability-{{ 'high' if item.article.reliability >= 0.9 else 'medium' if item.article.reliability >= 0.8 else 'low' }}">
                                {{ '%.0f'|format(item.article.reliability * 100) }}%
                            </span>
                        </div>
                    </div>
                    {% if item.ai_summary %}
                    <p class="article-summary">{{ item.ai_summary }}</p>
                    {% elif item.article.summary %}
                    <p class="article-summary">{{ item.article.summary[:200] }}{% if item.article.summary|length > 200 %}...{% endif %}</p>
                    {% endif %}
                    {% if item.why_it_matters %}
                    <p class="article-why">{{ item.why_it_matters }}</p>
                    {% endif %}
                </article>
                {% endfor %}
            </div>
        </div>
        {% endfor %}

        <footer>
            AI-curated news brief &middot; Auto-refreshes hourly &middot;
            <a href="https://github.com/axeandlord/news">Source</a>
        </footer>
    </div>

    <script>
        function toggleSection(header) {
            header.classList.toggle('collapsed');
            const content = header.nextElementSibling;
            content.classList.toggle('hidden');
        }
    </script>
</body>
</html>
"""


def generate_html(
    sections: dict[str, list[CuratedArticle]],
    audio_file: str | None = None,
    output_path: str = "index.html"
) -> str:
    """Generate HTML page from curated articles."""
    template = Template(HTML_TEMPLATE)

    now = datetime.now(timezone.utc)
    # Format: "Feb 4, 2026 at 11:30 AM UTC"
    updated = now.strftime("%b %-d, %Y at %-I:%M %p UTC")

    html = template.render(
        sections=sections,
        updated=updated,
        audio_file=audio_file,
    )

    Path(output_path).write_text(html)
    print(f"Generated {output_path}")

    return html


if __name__ == "__main__":
    # Test with mock data
    from .fetcher import Article
    from datetime import datetime, timezone

    test_article = Article(
        title="Test Article",
        link="https://example.com",
        summary="This is a test summary.",
        source="Test Source",
        published=datetime.now(timezone.utc),
        category="tech_ai",
        language="en",
        reliability=0.9,
    )

    test_curated = CuratedArticle(
        article=test_article,
        score=0.8,
        ai_summary="AI-generated summary here.",
        why_it_matters="This matters because...",
    )

    sections = {"Top Stories": [test_curated]}
    generate_html(sections)
