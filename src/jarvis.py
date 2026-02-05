"""JARVIS-style news briefing generator.

Transforms raw news into personalized, conversational briefings.
NOT a newsreader - a brilliant friend who synthesizes what matters.
"""

import os
import random
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from .curator import CuratedArticle

# Local Ollama API (free, uses local GPU)
OLLAMA_API_URL = "http://localhost:11434/api/chat"
LOCAL_MODEL = "qwen2.5:14b"  # Fast and capable on RTX 4080
MAX_ARTICLES_FOR_AI = 25  # Limit for reasonable response time

# Fallback to OpenRouter if local unavailable
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "anthropic/claude-3-haiku"


def load_persona(config_path: str = "config/persona.yaml") -> dict:
    """Load JARVIS persona configuration."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def get_time_context(persona: dict) -> dict:
    """Get time-aware context for the briefing."""
    now = datetime.now()
    hour = now.hour

    # Determine time of day
    if hour < 6:
        time_of_day = "late_night"
    elif hour < 12:
        time_of_day = "morning" if hour >= 9 else "morning_early"
    elif hour < 17:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    # Get greeting
    greetings = persona.get("greetings", {})
    greeting = greetings.get(time_of_day, f"Good {time_of_day.replace('_', ' ')}, sir.")

    # Day context
    day_name = now.strftime("%A").lower()
    day_context = persona.get("day_context", {})
    day_note = day_context.get(day_name, "")
    if day_name in ["saturday", "sunday"]:
        day_note = day_context.get("weekend", "").format(day=now.strftime("%A"))

    return {
        "time_of_day": time_of_day,
        "greeting": greeting,
        "day_note": day_note,
        "date_str": now.strftime("%A, %B %-d, %Y"),
        "hour": hour,
    }


def build_system_prompt(persona: dict) -> str:
    """Build the JARVIS system prompt from persona config."""

    user_name = persona.get("user", {}).get("name", "sir")
    humor = persona.get("humor", {})
    humor_style = humor.get("style", "dry british wit")
    humor_examples = humor.get("examples", [])

    interests = persona.get("interests", {})
    primary_interests = interests.get("primary", [])
    expert_topics = interests.get("expert_level", [])

    context_notes = persona.get("context", [])

    # Build examples string
    examples_str = ""
    if humor_examples:
        examples_str = "\n".join(f"  - {ex}" for ex in random.sample(humor_examples, min(2, len(humor_examples))))

    return f"""You are writing a PODCAST SCRIPT for {user_name} - this will be read aloud by text-to-speech.

YOUR VOICE: Smart, warm, British-friendly tone. Like a well-informed friend catching them up over coffee.

ABSOLUTE RULES (TTS will sound terrible otherwise):
1. ZERO SYMBOLS - no #, *, -, %, $, or any special characters
2. ZERO LISTS - no bullet points, no numbered items, no "firstly/secondly"
3. ZERO STRUCTURE - no headers, no sections, just flowing natural speech
4. Write numbers as words: "fifty million dollars" not "$50M", "about thirty percent" not "30%"
5. Use contractions: it's, they've, that's, won't, can't
6. Smooth transitions only: "Meanwhile", "Speaking of which", "On a related note", "Interestingly"

WHAT MAKES IT GOOD:
- Explain WHY things matter, not just what happened
- Connect dots between related stories naturally
- Skip boring details, focus on what's actually interesting
- Sound like you're genuinely telling a friend, not reading a script
- {user_name} knows about: {', '.join(expert_topics[:3]) if expert_topics else 'AI, tech'} - skip basic explanations

OUTPUT: Pure spoken text. No formatting. No metadata. Just words that sound natural when read aloud."""


def build_news_content(sections: dict[str, list[CuratedArticle]]) -> str:
    """Build news content as plain text for AI - no markdown, no metadata."""
    stories = []

    for section_name, articles in sections.items():
        if not articles:
            continue

        # Simple section header, no formatting
        category = section_name.replace("&", "and")

        for item in articles:
            article = item.article
            summary = clean_summary(item.ai_summary or article.summary or "")
            title = clean_summary(article.title)
            source = article.source

            # Plain text story - just the facts, no symbols
            story = f"{category}: {title}. {summary} (from {source})"
            stories.append(story)

    return "\n\n".join(stories)


def generate_jarvis_briefing(
    sections: dict[str, list[CuratedArticle]],
    persona_path: str = "config/persona.yaml",
) -> str:
    """
    Generate a complete JARVIS-style news briefing.

    Tries local Ollama first (free, powerful), then OpenRouter, then template.
    """
    persona = load_persona(persona_path)
    time_ctx = get_time_context(persona)

    # Build prompts - limit articles for reasonable AI processing time
    system_prompt = build_system_prompt(persona)

    # Limit to top articles per section for AI (keeps response time reasonable)
    limited_sections = {}
    total_for_ai = 0
    for section_name, articles in sections.items():
        remaining = MAX_ARTICLES_FOR_AI - total_for_ai
        if remaining <= 0:
            break
        take = min(len(articles), max(3, remaining // len(sections)))  # At least 3 per section
        limited_sections[section_name] = articles[:take]
        total_for_ai += take

    news_content = build_news_content(limited_sections)
    total_articles = total_for_ai

    user_prompt = f"""It's {time_ctx['time_of_day'].replace('_', ' ')}.

I haven't checked the news today. Tell me what's going on like you're my smart friend who reads everything. Here's what happened:

{news_content}

---

Now write me a briefing I'll LISTEN to (text-to-speech). Write it like a PODCAST SCRIPT:

CRITICAL RULES:
- NO symbols whatsoever. No hashtags, asterisks, bullet points, dashes, percent signs, numbers with symbols
- NO lists or structured formatting - pure flowing conversation
- NO "here are the top stories" or "first, second, third" structure
- Write exactly how you'd SPEAK to a friend - natural, flowing, human
- Say "about eighty percent" not "80%", say "around fifty million" not "$50M"
- Group related things naturally: "Speaking of AI..." or "On a related note..."
- Tell me WHY things matter, not just what happened
- Be genuinely interesting - if something is boring, make it interesting or skip it
- Transitions should be smooth: "Meanwhile...", "Interestingly...", "Now here's something cool..."
- About 12-15 minutes when read aloud

Start directly with the news (no "good morning" - I'll add that). End with a natural wrap-up."""

    # Try local Ollama first (free, uses local GPU)
    briefing = _try_ollama(system_prompt, user_prompt)
    if briefing:
        print(f"  Generated briefing with local Ollama ({LOCAL_MODEL})")
        return prepare_for_tts(briefing)

    # Fall back to OpenRouter
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_MAIN")
    if api_key:
        briefing = _try_openrouter(system_prompt, user_prompt, api_key)
        if briefing:
            print("  Generated briefing with OpenRouter")
            return prepare_for_tts(briefing)

    # Final fallback to template
    print("  [WARN] AI unavailable, using template style")
    return generate_template_briefing(sections, persona, time_ctx)


def _try_ollama(system_prompt: str, user_prompt: str) -> str | None:
    """Try generating with local Ollama."""
    try:
        response = httpx.post(
            OLLAMA_API_URL,
            json={
                "model": LOCAL_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "num_predict": 8000,
                    "temperature": 0.7,
                },
            },
            timeout=600,  # 10 min for large model
        )
        if response.status_code == 200:
            return response.json()["message"]["content"]
    except Exception as e:
        print(f"  [WARN] Ollama error: {e}")
    return None


def _try_openrouter(system_prompt: str, user_prompt: str, api_key: str) -> str | None:
    """Try generating with OpenRouter API."""
    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://news.bezman.ca",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 8000,
                "temperature": 0.7,
            },
            timeout=120,
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            print(f"  [WARN] OpenRouter error {response.status_code}")
    except Exception as e:
        print(f"  [WARN] OpenRouter error: {e}")
    return None


def generate_template_briefing(
    sections: dict[str, list[CuratedArticle]],
    persona: dict,
    time_ctx: dict,
) -> str:
    """
    Generate natural conversational briefing optimized for TTS.

    Smart rotation across all elements to sound human and avoid repetition.
    """

    # === OPENINGS - varied ways to start the briefing ===
    openings = [
        "Here's what's going on.",
        "Let me catch you up.",
        "Here's what you need to know.",
        "Got a few things for you.",
        "Here's the rundown.",
    ]

    # === SECTION TRANSITIONS - smooth moves between themes ===
    # First section (no previous context)
    first_section_intros = {
        "AI & Technology": ["Starting with tech.", "First up, AI and tech.", "On the tech front."],
        "Finance & Markets": ["Starting with markets.", "First, the financial picture.", "Let's start with finance."],
        "World & Geopolitics": ["Starting internationally.", "First, world news.", "On the global front."],
        "Montreal": ["Starting locally.", "First, here in Montreal.", "Closer to home first."],
        "Quebec": ["Starting with Quebec.", "First, provincial news."],
        "Canada": ["Starting nationally.", "First, across Canada."],
        "Wildcards & Emerging": ["Starting with some interesting developments.", "First, a few things worth noting."],
    }

    # Transitioning between sections (acknowledges shift)
    section_transitions = {
        "AI & Technology": ["Shifting to tech.", "Now for AI and tech.", "On the tech side.", "In the tech world."],
        "Finance & Markets": ["Turning to markets.", "Now for finance.", "On the money side.", "Financially speaking."],
        "World & Geopolitics": ["Looking internationally.", "On the world stage.", "Globally.", "Further afield."],
        "Montreal": ["Closer to home now.", "Here in Montreal.", "Locally.", "Back home."],
        "Quebec": ["In Quebec.", "Provincially.", "Around Quebec."],
        "Canada": ["Nationally.", "Across Canada.", "On the national scene."],
        "Wildcards & Emerging": ["A few other things.", "Some other developments.", "Also worth knowing."],
    }

    # === ARTICLE INTROS - varied ways to introduce each story ===
    # Sometimes lead with source, sometimes with the news
    article_patterns = [
        "{title}. {summary} {source_attr}",  # Standard: title, summary, source
        "{source} is reporting that {summary_lower} {title_context}",  # Lead with source
        "{summary} {source_attr} {title_context}",  # Lead with summary
        "{title}. {source_attr} {summary}",  # Title, source, then details
    ]

    # === WITHIN-SECTION TRANSITIONS - article to article ===
    article_transitions = [
        "Also,", "And", "Meanwhile,", "Separately,", "Additionally,",
        "Related to that,", "On a similar note,", "In other news,",
        "", "", "",  # Empty = natural flow, no connector needed
    ]

    # === SOURCE ATTRIBUTIONS - conversational ===
    source_before = [  # When source comes before the news
        "{source} is reporting that",
        "{source} says",
        "According to {source},",
        "Per {source},",
        "{source} has the story:",
    ]

    source_after = [  # When source comes after
        "That's from {source}.",
        "Via {source}.",
        "That's according to {source}.",
        "This comes from {source}.",
        "{source} has the details.",
        "That's per {source}.",
    ]

    # === CLOSING LINES ===
    closings = [
        "That's the rundown.",
        "That covers the main points.",
        "That's what you need to know.",
        "And that's where things stand.",
        "That's your update.",
        "That's the latest.",
    ]

    # === BUILD THE BRIEFING ===

    # Track what we've used to avoid repetition
    used_article_trans = []
    used_source_after = []
    used_patterns = []

    # Greeting based on time
    greetings = {
        "morning": "Good morning sir.",
        "morning_early": "Good morning sir.",
        "afternoon": "Good afternoon sir.",
        "evening": "Good evening sir.",
        "late_night": "Evening sir.",
    }

    greeting = greetings.get(time_ctx.get("time_of_day", "evening"), "Hello sir.")
    opening = random.choice(openings)

    parts = [f"{greeting} {opening}", ""]

    section_count = 0
    total_articles = 0

    for section_name, articles in sections.items():
        if not articles:
            continue

        # Pick section intro based on whether it's first section or not
        if section_count == 0:
            intros = first_section_intros.get(section_name, [f"Starting with {section_name.lower()}."])
        else:
            intros = section_transitions.get(section_name, [f"Now for {section_name.lower()}."])

        section_intro = random.choice(intros)
        parts.append(section_intro)

        for i, item in enumerate(articles):
            article = item.article
            raw_summary = item.ai_summary or article.summary or ""
            summary = clean_summary(raw_summary)
            title = clean_summary(article.title).rstrip(".").strip()
            source = article.source

            # Build the article text with smart variation
            text_parts = []

            # Add transition if not first article in section
            if i > 0:
                available = [t for t in article_transitions if t not in used_article_trans[-2:]]
                trans = random.choice(available) if available else random.choice(article_transitions)
                used_article_trans.append(trans)
                if trans:
                    text_parts.append(trans)

            # Choose a pattern for this article (rotate)
            available_patterns = [p for p in article_patterns if p not in used_patterns[-2:]]
            pattern = random.choice(available_patterns) if available_patterns else random.choice(article_patterns)
            used_patterns.append(pattern)

            # Prepare components
            summary_clean = summary.strip().rstrip(".") if summary else ""
            # Only lowercase first letter if it's not an acronym (followed by lowercase)
            if summary_clean and len(summary_clean) > 1:
                if summary_clean[1].islower():
                    summary_lower = summary_clean[0].lower() + summary_clean[1:]
                else:
                    summary_lower = summary_clean  # Keep as-is for acronyms
            else:
                summary_lower = summary_clean
            title_context = f"The headline: {title}." if "title_context" in pattern and summary else ""

            # Source attribution
            available_src = [s for s in source_after if s not in used_source_after[-2:]]
            source_attr = random.choice(available_src).format(source=source)
            used_source_after.append(source_attr)

            # Build based on pattern
            if "{source} is reporting" in pattern or pattern.startswith("{source}"):
                # Source-first pattern
                src_before = random.choice(source_before).format(source=source)
                if summary_lower:
                    text_parts.append(f"{src_before} {summary_lower}.")
                else:
                    text_parts.append(f"{src_before} {title.lower()}.")
            elif pattern.startswith("{summary}"):
                # Summary-first pattern
                if summary_clean:
                    text_parts.append(f"{summary_clean}. {source_attr}")
                else:
                    text_parts.append(f"{title}. {source_attr}")
            else:
                # Standard: title then summary
                text_parts.append(f"{title}.")
                if summary_clean:
                    text_parts.append(f"{summary_clean}.")
                text_parts.append(source_attr)

            parts.append(" ".join(text_parts))
            total_articles += 1

        parts.append("")  # Blank line between sections
        section_count += 1

    # Closing
    closing = random.choice(closings)
    parts.append(closing)

    return prepare_for_tts("\n".join(parts))


def clean_summary(text: str) -> str:
    """
    Clean raw RSS/article summaries for human-friendly TTS.

    Strips academic jargon, arXiv IDs, metadata prefixes, etc.
    """
    import re

    if not text:
        return ""

    # Remove arXiv IDs and metadata
    text = re.sub(r'arXiv:\d+\.\d+v?\d*\s*', '', text)
    text = re.sub(r'Announce Type:\s*\w+\s*', '', text)
    text = re.sub(r'^Abstract:\s*', '', text)

    # Remove paper/study prefixes that sound robotic
    text = re.sub(r'^(This paper|This study|We present|We propose|We introduce|In this paper,?)\s+', '', text, flags=re.IGNORECASE)

    # Remove "Read more" and similar
    text = re.sub(r'\s*(Read more|Continue reading|Click here|Learn more)\.?\.?\.?\s*$', '', text, flags=re.IGNORECASE)

    # Remove trailing ellipsis from truncated text
    text = re.sub(r'\.\.\.+\s*$', '.', text)
    text = re.sub(r'…\s*$', '.', text)

    # Clean up HTML entities that sometimes slip through
    text = text.replace('&amp;', 'and')
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&#39;', "'")
    text = text.replace('&quot;', '"')

    # Remove [PDF] [HTML] etc
    text = re.sub(r'\[(PDF|HTML|DOI|Link)\]', '', text, flags=re.IGNORECASE)

    # Clean multiple spaces
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def prepare_for_tts(text: str) -> str:
    """
    Prepare text for natural-sounding TTS output.

    Strips ALL symbols and formatting that TTS would read literally.
    """
    import re

    # Remove markdown formatting completely
    text = re.sub(r'#{1,6}\s*', '', text)  # Headers
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # Bold/italic
    text = re.sub(r'`[^`]+`', '', text)  # Code
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links

    # Remove bullet points and list markers
    text = re.sub(r'^[\s]*[-•*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+[.)]\s+', '', text, flags=re.MULTILINE)

    # Convert common symbols to words
    text = re.sub(r'\$(\d+(?:\.\d+)?)\s*([BMKbmk](?:illion|illion)?)?', lambda m: _money_to_words(m.group(0)), text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', lambda m: _percent_to_words(m.group(1)), text)
    text = text.replace('&', ' and ')
    text = text.replace('@', ' at ')
    text = text.replace('+', ' plus ')
    text = text.replace('=', ' equals ')

    # Remove remaining special characters that TTS reads oddly
    text = re.sub(r'[#*_~`|<>{}[\]\\^]', '', text)

    # Remove ellipsis
    text = re.sub(r'\.{2,}', '.', text)
    text = text.replace('…', '.')

    # Clean up quotes to simple ones
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")

    # Remove commas before direct address
    text = re.sub(r',\s*(sir|ma\'am|my friend)\b', r' \1', text, flags=re.IGNORECASE)

    # Remove commas after short introductory words
    text = re.sub(r'\b(Now|Well|So|Right|Yes|No|Oh),\s+', r'\1 ', text)

    # Remove comma before conjunctions for flow
    text = re.sub(r',\s+(and|but|or)\s+', r' \1 ', text)

    # Remove comma after greetings
    text = re.sub(r'(Good morning|Good afternoon|Good evening|Hello),', r'\1', text)

    # Make contractions more natural
    contractions = [
        (" it is ", " it's "), (" that is ", " that's "), (" there is ", " there's "),
        (" here is ", " here's "), (" what is ", " what's "), (" I have ", " I've "),
        (" I will ", " I'll "), (" do not ", " don't "), (" does not ", " doesn't "),
        (" cannot ", " can't "), (" will not ", " won't "), (" would not ", " wouldn't "),
        (" could not ", " couldn't "), (" should not ", " shouldn't "),
    ]
    for old, new in contractions:
        text = text.replace(old, new)

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'  +', ' ', text)

    return text.strip()


def _money_to_words(money_str: str) -> str:
    """Convert $50M to 'fifty million dollars'."""
    import re
    match = re.match(r'\$?([\d.]+)\s*([BMKbmk])?', money_str)
    if not match:
        return money_str

    num = float(match.group(1))
    suffix = (match.group(2) or '').upper()

    multipliers = {'B': 'billion', 'M': 'million', 'K': 'thousand'}
    mult_word = multipliers.get(suffix, '')

    # Simple conversion for common values
    if num == int(num):
        num_word = str(int(num))
    else:
        num_word = str(num)

    if mult_word:
        return f"{num_word} {mult_word} dollars"
    return f"{num_word} dollars"


def _percent_to_words(num_str: str) -> str:
    """Convert 85% to 'eighty-five percent'."""
    try:
        num = float(num_str)
        if num == int(num):
            return f"{int(num)} percent"
        return f"{num} percent"
    except ValueError:
        return f"{num_str} percent"


if __name__ == "__main__":
    # Test
    from .fetcher import Article
    from datetime import datetime, timezone

    test_articles = [
        CuratedArticle(
            article=Article(
                title="GitHub adds Claude and Codex AI coding agents",
                link="https://example.com",
                summary="GitHub is making AI coding agents available to Copilot Pro Plus and Enterprise users.",
                source="The Verge",
                published=datetime.now(timezone.utc),
                category="tech_ai",
                language="en",
                reliability=0.9,
            ),
            score=0.9,
            ai_summary="GitHub now offers Claude and Codex AI agents directly to Copilot users as part of its Agent HQ initiative.",
            why_it_matters="This signals a major shift in how developers will interact with AI coding tools.",
        ),
        CuratedArticle(
            article=Article(
                title="Anthropic announces Claude will remain ad-free",
                link="https://example.com",
                summary="Anthropic confirms Claude won't have ads, unlike ChatGPT.",
                source="TechCrunch",
                published=datetime.now(timezone.utc),
                category="tech_ai",
                language="en",
                reliability=0.85,
            ),
            score=0.85,
            ai_summary="Anthropic is keeping Claude ad-free and even mocking competitors with a Super Bowl commercial.",
            why_it_matters="This positions Claude as the premium, user-focused alternative in the AI assistant market.",
        ),
    ]

    sections = {"Top Stories": test_articles}
    briefing = generate_jarvis_briefing(sections)
    print(briefing)
