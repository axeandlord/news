#!/usr/bin/env python3
"""
Local News Reader with Edge TTS

Read news briefs aloud using Microsoft's neural TTS voices.
Supports reading summaries or fetching full article content.

Usage:
    python src/local_reader.py           # Read today's brief (summaries)
    python src/local_reader.py --full    # Read with full articles
    python src/local_reader.py --date 2026-02-03  # Read archived date
    python src/local_reader.py --file index.html  # Read local file

Interactive controls during playback:
    [Space] - Pause/Resume
    [N]     - Next article
    [F]     - Fetch & read full article (if in brief mode)
    [Q]     - Quit
"""

import argparse
import asyncio
import io
import random
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import edge_tts
import httpx
import subprocess
from bs4 import BeautifulSoup

# Article extraction
try:
    from newspaper import Article as NewsArticle
    HAS_NEWSPAPER = True
except ImportError:
    HAS_NEWSPAPER = False

try:
    from readability import Document as ReadabilityDoc
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False


NEWS_URL = "https://news.bezman.ca"
ARCHIVE_URL = f"{NEWS_URL}/archive"

# JARVIS-style British voice
VOICE_EN = "en-GB-RyanNeural"  # British male, warm and intelligent


@dataclass
class NewsItem:
    """Parsed news item from HTML."""
    section: str
    title: str
    source: str
    summary: str
    link: str
    why_it_matters: str | None = None


def parse_news_html(html: str) -> list[NewsItem]:
    """Parse news brief HTML into structured items."""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for section_div in soup.find_all("div", class_="section"):
        # Get section name
        header = section_div.find("h2")
        if not header:
            continue
        section_name = header.get_text(strip=True)

        # Get articles in this section
        for article in section_div.find_all("article", class_="article"):
            title_elem = article.find("h3", class_="article-title")
            if not title_elem:
                continue

            link_elem = title_elem.find("a")
            title = title_elem.get_text(strip=True)
            link = link_elem.get("href", "") if link_elem else ""

            source_elem = article.find("span", class_="article-source")
            source = source_elem.get_text(strip=True) if source_elem else ""

            summary_elem = article.find("p", class_="article-summary")
            summary = summary_elem.get_text(strip=True) if summary_elem else ""

            why_elem = article.find("p", class_="article-why")
            why = why_elem.get_text(strip=True) if why_elem else None

            items.append(NewsItem(
                section=section_name,
                title=title,
                source=source,
                summary=summary,
                link=link,
                why_it_matters=why,
            ))

    return items


def fetch_news_html(source: str = "today") -> str:
    """
    Fetch news HTML from URL or file.

    Args:
        source: "today", "YYYY-MM-DD", or file path
    """
    if source == "today":
        url = f"{NEWS_URL}/index.html"
    elif re.match(r"\d{4}-\d{2}-\d{2}", source):
        url = f"{ARCHIVE_URL}/{source}.html"
    elif Path(source).exists():
        return Path(source).read_text()
    else:
        url = source

    print(f"Fetching {url}...")
    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_full_article(url: str) -> str | None:
    """
    Fetch full article content, bypassing paywalls when possible.

    Tries multiple strategies in order:
    1. newspaper3k - works for most sites without JS paywalls
    2. readability-lxml - better text extraction
    3. Direct HTML fetch as fallback
    """
    # Strategy 1: newspaper3k
    if HAS_NEWSPAPER:
        try:
            article = NewsArticle(url)
            article.download()
            article.parse()
            if article.text and len(article.text) > 200:
                return clean_article_text(article.text)
        except Exception:
            pass

    # Strategy 2: readability-lxml
    if HAS_READABILITY:
        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NewsReader/1.0)"}
            )
            doc = ReadabilityDoc(response.text)
            # Extract text from readability's cleaned HTML
            soup = BeautifulSoup(doc.summary(), "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if text and len(text) > 200:
                return clean_article_text(text)
        except Exception:
            pass

    # Strategy 3: Direct fetch with basic extraction
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsReader/1.0)"}
        )
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script, style, nav elements
        for elem in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
            elem.decompose()

        # Try common article containers
        article_content = None
        for selector in ["article", "[role='main']", ".article-content", ".post-content", "main"]:
            article_content = soup.select_one(selector)
            if article_content:
                break

        if article_content:
            text = article_content.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return clean_article_text(text)
    except Exception:
        pass

    return None


def clean_article_text(text: str) -> str:
    """Clean extracted article text for TTS."""
    # Remove multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove common boilerplate phrases
    boilerplate = [
        r"Subscribe to.*?newsletter",
        r"Sign up for.*?newsletter",
        r"Read more:.*",
        r"Related:.*",
        r"Advertisement",
        r"ADVERTISEMENT",
        r"Share this article",
        r"Follow us on.*",
        r"Copyright.*\d{4}",
    ]
    for pattern in boilerplate:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    return text.strip()


# JARVIS-style transitions with subtle wit
TRANSITIONS = [
    "Moving on to something rather interesting,",
    "In other developments worth your attention,",
    "You might find this one noteworthy as well,",
    "Next on the agenda,",
    "Meanwhile, in related matters,",
    "Here's another item of interest,",
    "I should also mention,",
]

SECTION_INTROS = {
    "Top Stories": "Let's begin with today's most significant developments.",
    "Tech & AI": "Now then, the latest from the world of technology and artificial intelligence.",
    "Montreal & Quebec": "Turning to matters closer to home in Montreal and Quebec.",
    "Business & Markets": "On the financial front,",
    "Science & Health": "In science and health news, which I suspect you'll find quite fascinating,",
    "World News": "From around the globe,",
}


def prepare_text_for_tts(item: NewsItem, full_text: str | None = None, is_first: bool = False) -> str:
    """
    Prepare text for natural news delivery.

    Args:
        item: Parsed news item
        full_text: Full article text if fetched, else use summary
        is_first: Whether this is the first article (no transition needed)
    """
    parts = []

    # Add transition for non-first articles
    if not is_first:
        parts.append(random.choice(TRANSITIONS))

    # Natural headline intro (not just the raw title)
    title = item.title.rstrip(".")
    parts.append(f"{title}.")

    # Content with natural flow
    if full_text:
        parts.append(full_text)
    elif item.summary:
        # Clean up summary for natural reading
        summary = item.summary.strip()
        if not summary.endswith((".", "!", "?")):
            summary += "."
        parts.append(summary)

    # Why it matters - frame it naturally
    if item.why_it_matters and not full_text:
        why = item.why_it_matters.strip()
        if not why.endswith((".", "!", "?")):
            why += "."
        parts.append(why)

    # Add source attribution naturally
    parts.append(f"That's according to {item.source}.")

    return " ".join(parts)


def get_section_intro(section_name: str) -> str:
    """Get natural intro for a section."""
    return SECTION_INTROS.get(section_name, f"Now, {section_name.lower()}.")


def get_news_intro() -> str:
    """Get JARVIS-style intro for the news broadcast."""
    now = datetime.now()
    time_of_day = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    date_str = now.strftime("%A, %B %-d")

    intros = [
        f"Good {time_of_day}, sir. I've prepared your news brief for {date_str}.",
        f"Good {time_of_day}, sir. Here's what you need to know for {date_str}.",
        f"Good {time_of_day}. I've curated today's most relevant stories for your attention.",
    ]
    return random.choice(intros)


def get_news_outro() -> str:
    """Get JARVIS-style outro for the news broadcast."""
    outros = [
        "And that concludes your briefing, sir. Will there be anything else?",
        "That's all for now, sir. I'll keep monitoring for anything noteworthy.",
        "And that wraps up today's brief. As always, I remain at your service.",
    ]
    return random.choice(outros)


class EdgeTTSReader:
    """Edge TTS reader with ffplay playback."""

    def __init__(self, voice: str = VOICE_EN):
        self.voice = voice

        # Playback state
        self.paused = False
        self.skip = False
        self.quit = False
        self.fetch_full = False
        self._player_process: subprocess.Popen | None = None

        print(f"Using voice: {self.voice}")

    async def _generate_audio(self, text: str) -> bytes:
        """Generate audio bytes from text using Edge TTS."""
        communicate = edge_tts.Communicate(text, self.voice)

        audio_data = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.write(chunk["data"])

        return audio_data.getvalue()

    def _play_audio(self, audio_data: bytes) -> None:
        """Play audio data through ffplay."""
        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        try:
            # Start ffplay process
            self._player_process = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for playback, checking for skip/quit
            while self._player_process.poll() is None:
                if self.quit or self.skip:
                    self._player_process.terminate()
                    self._player_process.wait(timeout=1)
                    if self.skip:
                        self.skip = False
                    break
                time.sleep(0.05)

            self._player_process = None
        finally:
            # Cleanup temp file
            Path(temp_path).unlink(missing_ok=True)

    def speak(self, text: str) -> None:
        """Generate and play speech for text."""
        if not text.strip():
            return

        # Generate audio
        audio_data = asyncio.run(self._generate_audio(text))

        # Play it
        self._play_audio(audio_data)

    def read_news(self, items: list[NewsItem], full_mode: bool = False) -> None:
        """
        Read news items aloud with natural delivery.

        Args:
            items: List of news items to read
            full_mode: If True, fetch full articles by default
        """
        # Group by section
        sections: dict[str, list[NewsItem]] = {}
        for item in items:
            if item.section not in sections:
                sections[item.section] = []
            sections[item.section].append(item)

        print("\n" + "=" * 50)
        print("NEWS BRIEF")
        print("=" * 50)
        print("Controls: [Space] Pause | [N] Next | [Q] Quit")
        print("=" * 50 + "\n")

        # Start keyboard listener
        self._start_keyboard_listener()

        try:
            # Natural intro
            intro = get_news_intro()
            print(f"[Intro] {intro}")
            self.speak(intro)
            time.sleep(0.5)

            is_first_article = True

            for section_name, section_items in sections.items():
                if self.quit:
                    break

                # Natural section intro
                section_intro = get_section_intro(section_name)
                print(f"\n[{section_name}] {section_intro}")
                self.speak(section_intro)
                time.sleep(0.3)

                for i, item in enumerate(section_items, 1):
                    if self.quit:
                        break

                    print(f"  [{i}/{len(section_items)}] {item.title}")

                    # Determine if we should fetch full article
                    fetch_full = full_mode or self.fetch_full
                    self.fetch_full = False

                    full_text = None
                    if fetch_full:
                        print("    Fetching full article...")
                        full_text = fetch_full_article(item.link)
                        if full_text:
                            print(f"    Got {len(full_text)} chars")
                        else:
                            print("    Using summary")

                    # Prepare and speak with natural delivery
                    text = prepare_text_for_tts(item, full_text, is_first=is_first_article)
                    self.speak(text)
                    is_first_article = False

                    # Natural pause between articles
                    if not self.skip:
                        time.sleep(0.4)

        finally:
            self._stop_keyboard_listener()

        if not self.quit:
            # Natural outro
            outro = get_news_outro()
            print(f"\n[Outro] {outro}")
            self.speak(outro)

    def _start_keyboard_listener(self) -> None:
        """Start keyboard listener for controls."""
        try:
            import termios
            import tty

            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

            self._kb_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
            self._kb_thread.start()
        except Exception:
            print("(Keyboard controls not available)")

    def _stop_keyboard_listener(self) -> None:
        """Restore terminal settings."""
        try:
            import termios
            if hasattr(self, "_old_settings"):
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
        except Exception:
            pass

    def _keyboard_loop(self) -> None:
        """Process keyboard input."""
        while not self.quit:
            try:
                char = sys.stdin.read(1).lower()
                if char == " ":
                    self.paused = not self.paused
                    status = "PAUSED" if self.paused else "RESUMED"
                    print(f"\r[{status}]", end="", flush=True)
                elif char == "n":
                    self.skip = True
                    print("\r[SKIP]", end="", flush=True)
                elif char == "f":
                    self.fetch_full = True
                    print("\r[FULL]", end="", flush=True)
                elif char == "q":
                    self.quit = True
                    print("\r[QUIT]", end="", flush=True)
                    break
            except Exception:
                break


async def list_voices():
    """List available Edge TTS voices."""
    voices = await edge_tts.list_voices()
    en_voices = [v for v in voices if v["Locale"].startswith("en-")]
    print("\nAvailable English voices:")
    for v in en_voices[:10]:
        print(f"  {v['ShortName']}: {v['Gender']}")


def main():
    parser = argparse.ArgumentParser(
        description="Read news briefs aloud with Edge TTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Fetch and read full articles (bypasses paywalls when possible)"
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Read archived brief from specific date"
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="Read from local HTML file"
    )
    parser.add_argument(
        "--voice",
        default=VOICE_EN,
        help=f"Voice to use (default: {VOICE_EN})"
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List available voices and exit"
    )

    args = parser.parse_args()

    if args.list_voices:
        asyncio.run(list_voices())
        return

    # Determine source
    if args.file:
        source = args.file
    elif args.date:
        source = args.date
    else:
        source = "today"

    # Fetch and parse news
    try:
        html = fetch_news_html(source)
    except httpx.HTTPError as e:
        print(f"Error fetching news: {e}")
        sys.exit(1)

    items = parse_news_html(html)
    if not items:
        print("No news items found!")
        sys.exit(1)

    print(f"Found {len(items)} news items")

    # Initialize reader
    reader = EdgeTTSReader(voice=args.voice)

    # Read news
    reader.read_news(items, full_mode=args.full)


if __name__ == "__main__":
    main()
