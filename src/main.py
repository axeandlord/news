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
from src.tts import (
    generate_audio_brief,
    generate_audio_brief_fr,
    generate_deep_dive_audio,
    generate_deep_dive_audio_fr,
)
from src.archive import archive_brief


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
        "--no-research",
        action="store_true",
        help="Skip Tavily web research"
    )
    parser.add_argument(
        "--no-deep-dive",
        action="store_true",
        help="Skip deep dive generation"
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
    print("\n[1/7] Fetching RSS feeds...")
    articles = fetch_feeds_sync(args.feeds_config)

    if not articles:
        print("ERROR: No articles fetched!")
        sys.exit(1)

    # Step 2: Curate and score articles
    print("\n[2/7] Curating articles...")
    if args.no_ai:
        import os
        os.environ.pop("OPENROUTER_API_KEY", None)

    sections = curate_articles(articles, args.curation_config)

    total_curated = sum(len(items) for items in sections.values())
    print(f"  Curated {total_curated} articles into {len(sections)} sections")

    # Step 3: Research top stories (Tavily)
    if not args.no_research:
        print("\n[3/7] Researching top stories...")
        try:
            from src.researcher import NewsResearcher
            researcher = NewsResearcher()
            if researcher.is_available():
                # Flatten top articles by score
                all_articles = []
                for section_articles in sections.values():
                    all_articles.extend(section_articles)
                all_articles.sort(key=lambda a: a.score, reverse=True)
                top_articles = all_articles[:12]

                results = researcher.research_articles(top_articles, max_queries=8)

                # Attach research context to top articles
                if results:
                    result_dicts = [
                        {"title": r.title, "url": r.url, "content": r.content, "score": r.score}
                        for r in results
                    ]
                    # Distribute results to top articles by relevance
                    for article in top_articles[:8]:
                        article.research_context = result_dicts[:4]
                    print(f"  Attached research context to top articles")
            else:
                print("  [WARN] Tavily API not available, skipping research")
        except Exception as e:
            print(f"  [WARN] Research failed: {e}")
    else:
        print("\n[3/7] Skipping research (--no-research)")

    # Step 4: Generate TTS audio
    audio_file = None
    audio_file_fr = None
    segments_en = None
    segments_fr = None
    en_segments_list = None
    if not args.no_tts:
        print("\n[4/7] Generating audio brief...")
        audio_file, en_segments_list, segments_en = generate_audio_brief(sections)
        if audio_file:
            print(f"  English audio: {audio_file}")
            if segments_en and segments_en.get("segments"):
                from src.database import record_briefing_segments
                briefing_id = segments_en.get("generated_at", "unknown")
                record_briefing_segments(briefing_id, segments_en["segments"])
        else:
            print("  English audio generation skipped or failed")

        # Generate French audio
        print("  Generating French audio brief...")
        audio_file_fr, segments_fr = generate_audio_brief_fr(sections, en_segments=en_segments_list)
        if audio_file_fr:
            print(f"  French audio: {audio_file_fr}")
        else:
            print("  French audio generation skipped or failed")
    else:
        print("\n[4/7] Skipping TTS (--no-tts)")

    # Step 5: Generate deep dives
    deep_dives = []
    if not args.no_deep_dive and not args.no_tts:
        print("\n[5/7] Generating deep dives...")
        try:
            from src.deep_dive import load_deep_dive_config, select_deep_dive_topics, generate_deep_dive
            from src.researcher import NewsResearcher

            dd_config = load_deep_dive_config()
            if dd_config.get("deep_dive", {}).get("enabled", False):
                dd_topics = select_deep_dive_topics(sections, dd_config)

                researcher = NewsResearcher()

                for topic in dd_topics:
                    topic_name = topic["config"]["name"]
                    category = topic["config"]["category"]

                    # Generate deep dive script + segments
                    dd_segments = generate_deep_dive(topic, researcher)

                    if dd_segments:
                        # Generate EN audio
                        dd_audio, dd_meta = generate_deep_dive_audio(
                            category, dd_segments
                        )

                        # Generate FR audio
                        dd_audio_fr, dd_meta_fr = generate_deep_dive_audio_fr(
                            category, dd_segments
                        )

                        # Calculate total duration
                        total_duration = sum(
                            s.get("duration", 0)
                            for s in (dd_meta or {}).get("segments", [])
                        )
                        duration_min = int(total_duration / 60)
                        duration_label = f"~{duration_min} min" if duration_min > 0 else "~1 min"

                        deep_dives.append({
                            "topic": topic_name,
                            "category": category,
                            "summary": f"Deep analytical dive into today's {topic_name.lower()} stories.",
                            "duration_label": duration_label,
                            "source_count": len(topic["articles"]),
                            "audio_en": dd_audio,
                            "audio_fr": dd_audio_fr,
                            "segments_en": dd_meta,
                            "segments_fr": dd_meta_fr,
                        })
                        print(f"  Deep dive ready: {topic_name} ({duration_label})")
            else:
                print("  Deep dives disabled in config")
        except Exception as e:
            print(f"  [WARN] Deep dive generation failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\n[5/7] Skipping deep dives")

    # Step 6: Generate HTML
    print("\n[6/7] Generating HTML...")
    generate_html(
        sections,
        audio_file=audio_file,
        audio_file_fr=audio_file_fr,
        segments_en=segments_en,
        segments_fr=segments_fr,
        deep_dives=deep_dives,
        output_path=args.output,
    )

    # Step 7: Archive today's brief
    print("\n[7/7] Archiving brief...")
    archive_brief(
        html_path=args.output,
        article_count=total_curated,
        has_audio=audio_file is not None,
    )

    print("\n" + "=" * 50)
    print("DONE!")
    print(f"Output: {args.output}")
    if deep_dives:
        print(f"Deep dives: {len(deep_dives)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
