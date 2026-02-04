#!/usr/bin/env python3
"""News aggregator main orchestrator."""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fetcher import fetch_feeds_sync
from src.curator import curate_articles
from src.generator import generate_html
from src.tts import generate_audio_brief


def main():
    parser = argparse.ArgumentParser(description="AI-curated news aggregator")
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Skip TTS audio generation"
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip AI summaries (faster, no API cost)"
    )
    parser.add_argument(
        "--feeds-config",
        default="config/feeds.yaml",
        help="Path to feeds config"
    )
    parser.add_argument(
        "--curation-config",
        default="config/curation.yaml",
        help="Path to curation config"
    )
    parser.add_argument(
        "--output",
        default="index.html",
        help="Output HTML file path"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("NEWS BRIEF GENERATOR")
    print("=" * 50)

    # Step 1: Fetch all RSS feeds
    print("\n[1/4] Fetching RSS feeds...")
    articles = fetch_feeds_sync(args.feeds_config)

    if not articles:
        print("ERROR: No articles fetched!")
        sys.exit(1)

    # Step 2: Curate and score articles
    print("\n[2/4] Curating articles...")
    if args.no_ai:
        import os
        os.environ.pop("OPENROUTER_API_KEY", None)

    sections = curate_articles(articles, args.curation_config)

    total_curated = sum(len(items) for items in sections.values())
    print(f"  Curated {total_curated} articles into {len(sections)} sections")

    # Step 3: Generate TTS audio (optional)
    audio_file = None
    if not args.no_tts:
        print("\n[3/4] Generating audio brief...")
        audio_file = generate_audio_brief(sections)
        if audio_file:
            print(f"  Audio: {audio_file}")
        else:
            print("  Audio generation skipped or failed")
    else:
        print("\n[3/4] Skipping TTS (--no-tts)")

    # Step 4: Generate HTML
    print("\n[4/4] Generating HTML...")
    generate_html(sections, audio_file=audio_file, output_path=args.output)

    print("\n" + "=" * 50)
    print("DONE!")
    print(f"Output: {args.output}")
    print("=" * 50)


if __name__ == "__main__":
    main()
