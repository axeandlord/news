"""Archive utilities for news briefs."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

ARCHIVE_DIR = Path("archive")

ARCHIVE_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Brief Archive | news.bezman.ca</title>
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

        .subtitle {
            color: #707070;
            font-size: 0.875rem;
        }

        .back-link {
            display: inline-block;
            margin-bottom: 1.5rem;
            color: #9a8a9f;
            text-decoration: none;
            font-size: 0.9rem;
        }

        .back-link:hover {
            text-decoration: underline;
        }

        .archive-list {
            list-style: none;
        }

        .archive-item {
            background: #242429;
            border: 1px solid #3a3a40;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 0.75rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: border-color 0.2s;
        }

        .archive-item:hover {
            border-color: #9a8a9f;
        }

        .archive-item a {
            color: #e8e6e3;
            text-decoration: none;
            font-weight: 500;
        }

        .archive-item a:hover {
            color: #9a8a9f;
        }

        .archive-meta {
            display: flex;
            gap: 1rem;
            font-size: 0.8rem;
            color: #707070;
        }

        .archive-meta span {
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }

        .has-audio {
            color: #9a8a9f;
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

            .archive-item {
                flex-direction: column;
                align-items: flex-start;
                gap: 0.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>News Brief Archive</h1>
            <p class="subtitle">{{ total_briefs }} archived briefs</p>
        </header>

        <a href="../index.html" class="back-link">&larr; Today's Brief</a>

        <ul class="archive-list">
            {% for entry in entries %}
            <li class="archive-item">
                <a href="{{ entry.filename }}">{{ entry.date_display }}</a>
                <div class="archive-meta">
                    <span>{{ entry.article_count }} articles</span>
                    {% if entry.has_audio %}
                    <span class="has-audio">&#9835; Audio</span>
                    {% endif %}
                </div>
            </li>
            {% endfor %}
        </ul>

        <footer>
            AI-curated news briefs &middot;
            <a href="https://github.com/axeandlord/news">Source</a>
        </footer>
    </div>
</body>
</html>
"""


def archive_today(html_path: str = "index.html") -> str | None:
    """
    Copy today's index.html to archive/YYYY-MM-DD.html.

    Returns the archive filename if successful, None otherwise.
    """
    html_path = Path(html_path)
    if not html_path.exists():
        print(f"  Error: {html_path} not found")
        return None

    # Create archive directory if needed
    ARCHIVE_DIR.mkdir(exist_ok=True)

    # Generate dated filename
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_filename = f"{today}.html"
    archive_path = ARCHIVE_DIR / archive_filename

    # Copy index.html to archive
    shutil.copy(html_path, archive_path)
    print(f"  Archived to {archive_path}")

    return archive_filename


def update_manifest(
    date: str,
    article_count: int,
    has_audio: bool = False,
) -> None:
    """
    Update archive manifest.json with metadata for a brief.

    Args:
        date: Date string in YYYY-MM-DD format
        article_count: Number of articles in the brief
        has_audio: Whether the brief has audio
    """
    manifest_path = ARCHIVE_DIR / "manifest.json"

    # Load existing manifest or create new
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"briefs": []}

    # Check if date already exists, update if so
    existing = next(
        (b for b in manifest["briefs"] if b["date"] == date),
        None
    )

    entry = {
        "date": date,
        "article_count": article_count,
        "has_audio": has_audio,
        "filename": f"{date}.html",
    }

    if existing:
        existing.update(entry)
    else:
        manifest["briefs"].append(entry)

    # Sort by date descending (newest first)
    manifest["briefs"].sort(key=lambda x: x["date"], reverse=True)

    # Save manifest
    manifest_path.write_text(json.dumps(manifest, indent=2))


def generate_archive_index() -> None:
    """Generate archive/index.html from manifest."""
    manifest_path = ARCHIVE_DIR / "manifest.json"

    if not manifest_path.exists():
        print("  No manifest.json found, skipping archive index")
        return

    manifest = json.loads(manifest_path.read_text())

    # Format dates for display
    entries = []
    for brief in manifest["briefs"]:
        # Parse date and format nicely
        date_obj = datetime.strptime(brief["date"], "%Y-%m-%d")
        date_display = date_obj.strftime("%B %-d, %Y")  # "February 4, 2026"

        entries.append({
            "date": brief["date"],
            "date_display": date_display,
            "filename": brief["filename"],
            "article_count": brief["article_count"],
            "has_audio": brief.get("has_audio", False),
        })

    # Render template
    template = Template(ARCHIVE_INDEX_TEMPLATE)
    html = template.render(
        entries=entries,
        total_briefs=len(entries),
    )

    # Write archive index
    index_path = ARCHIVE_DIR / "index.html"
    index_path.write_text(html)
    print(f"  Generated {index_path}")


def archive_brief(
    html_path: str = "index.html",
    article_count: int = 0,
    has_audio: bool = False,
) -> None:
    """
    Archive today's brief: copy HTML, update manifest, regenerate index.

    Args:
        html_path: Path to the generated index.html
        article_count: Total number of curated articles
        has_audio: Whether audio was generated
    """
    print("Archiving today's brief...")

    # Archive the HTML
    filename = archive_today(html_path)
    if not filename:
        return

    # Get today's date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Update manifest
    update_manifest(today, article_count, has_audio)

    # Regenerate archive index
    generate_archive_index()

    print("  Archive complete")
