"""HTML generator for BRIEF news application."""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .curator import CuratedArticle
from .audio_processor import get_audio_info
from .jarvis import clean_summary


def generate_html(
    sections: dict[str, list[CuratedArticle]],
    audio_file: str | None = None,
    output_path: str = "index.html"
) -> str:
    """
    Generate HTML page from curated articles using templates.

    Args:
        sections: Dict of section name to curated articles
        audio_file: Path to audio file relative to output (e.g., "audio/brief-en.mp3")
        output_path: Output HTML file path

    Returns:
        Generated HTML string
    """
    # Set up Jinja2 environment
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Add filter to clean summaries for display
    env.filters['clean_summary'] = clean_summary

    # Load template
    template = env.get_template("index.html")

    # Calculate metadata - use local time for display
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Montreal"))
    date_display = now.strftime("%B %-d, %Y")

    article_count = sum(len(items) for items in sections.values())

    # Get audio duration if available
    duration = "~4 min"
    if audio_file:
        audio_path = Path(audio_file)
        if audio_path.exists():
            info = get_audio_info(str(audio_path))
            if info.get("duration_str"):
                duration = info["duration_str"]

    # Render template
    html = template.render(
        sections=sections,
        audio_file=audio_file,
        date_display=date_display,
        article_count=article_count,
        duration=duration,
    )

    # Write output
    Path(output_path).write_text(html)
    print(f"Generated {output_path}")

    # Copy static files to output directory
    copy_static_files(Path(output_path).parent)

    # Generate about page
    generate_about_page(Path(output_path).parent)

    return html


def copy_static_files(output_dir: Path) -> None:
    """Copy static CSS and JS files to output directory."""
    static_src = Path(__file__).parent.parent / "static"
    static_dst = output_dir.resolve() / "static"

    # If source and destination are the same (output in project root), skip copy
    if static_src.resolve() == static_dst:
        print(f"  Static files already in place at {static_dst}")
        return

    if static_src.exists():
        # Copy entire static directory
        if static_dst.exists():
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)
        print(f"  Copied static files to {static_dst}")


def generate_about_page(output_dir: Path) -> None:
    """Generate the about.html page."""
    template_dir = Path(__file__).parent.parent / "templates"
    about_template = template_dir / "about.html"

    if about_template.exists():
        output_path = output_dir / "about.html"
        shutil.copy(about_template, output_path)
        print(f"  Generated {output_path}")


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
