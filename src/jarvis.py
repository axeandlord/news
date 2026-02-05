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

# OpenRouter API for AI rewriting
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-3-haiku"  # Fast and cheap for summaries


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

    return f"""You are a professional news briefing assistant delivering a personalized summary to {user_name}.

STYLE:
- Professional, clear, informative
- British accent friendly tone
- Address as "{user_name}" occasionally but not every sentence
- Conversational but not trying to be funny

CRITICAL RULES FOR TTS OUTPUT:
1. NEVER attempt jokes, punchlines, or comedic timing - TTS cannot deliver humor
2. NEVER use phrases like "make of that what you will" or sarcastic asides - they sound flat
3. SYNTHESIZE don't recite - tell what MATTERS, not headlines
4. Connect related stories when relevant
5. Be direct and informative - wit comes from smart word choice, not delivery
6. Use contractions naturally (it's, they've, that's)
7. Skip context for topics they know: {', '.join(expert_topics[:3]) if expert_topics else 'AI, tech'}
8. Keep transitions smooth and natural

AVOID THESE (sound bad with TTS):
- "About time if you ask me"
- "Make of that what you will"
- "On the lighter side..."
- Any setup-punchline structure
- Dramatic pauses or ellipsis for effect

THEIR INTERESTS:
{chr(10).join(f'- {i}' for i in primary_interests) if primary_interests else '- AI and technology'}

OUTPUT FORMAT:
- Output ONLY the briefing text, no headers or metadata
- Natural spoken language optimized for text-to-speech
- Keep it under 800 words total
- End with a simple closing, not a question"""


def build_news_content(sections: dict[str, list[CuratedArticle]]) -> str:
    """Build news content string for AI processing."""
    parts = []

    for section_name, articles in sections.items():
        if not articles:
            continue

        parts.append(f"## {section_name}")

        for item in articles:
            article = item.article
            summary = item.ai_summary or article.summary
            why = item.why_it_matters or ""

            parts.append(f"""
**{article.title}**
Source: {article.source} (reliability: {article.reliability:.0%})
Summary: {summary}
{f"Context: {why}" if why else ""}
""")

    return "\n".join(parts)


def generate_jarvis_briefing(
    sections: dict[str, list[CuratedArticle]],
    persona_path: str = "config/persona.yaml",
) -> str:
    """
    Generate a complete JARVIS-style news briefing.

    Uses AI to create a conversational, personalized summary.
    Falls back to template-based generation if API unavailable.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_MAIN")
    persona = load_persona(persona_path)
    time_ctx = get_time_context(persona)

    if not api_key:
        print("  [WARN] No OPENROUTER_API_KEY, using template-based JARVIS style")
        return generate_template_briefing(sections, persona, time_ctx)

    # Build the system prompt
    system_prompt = build_system_prompt(persona)

    # Build the news content
    news_content = build_news_content(sections)

    # Count articles
    total_articles = sum(len(items) for items in sections.values())

    # User prompt
    user_prompt = f"""It's {time_ctx['time_of_day'].replace('_', ' ')} on {time_ctx['date_str']}.

Brief me on today's {total_articles} stories. Here they are:

{news_content}

Create a flowing, conversational briefing that:
1. Opens naturally (don't repeat the date I just told you)
2. Groups related stories when they connect
3. Adds insight and opinion, not just facts
4. Includes your trademark dry wit where appropriate
5. Closes with a natural sign-off

Remember: You're a brilliant assistant catching me up, not reading the news at me."""

    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://news.bezman.ca",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 2000,
                "temperature": 0.7,
            },
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            briefing = result["choices"][0]["message"]["content"]
            print("  Generated JARVIS briefing with AI")
            return prepare_for_tts(briefing)
        else:
            print(f"  [WARN] API error {response.status_code}, using template style")
            return generate_template_briefing(sections, persona, time_ctx)

    except Exception as e:
        print(f"  [WARN] AI briefing failed: {e}, using template style")
        return generate_template_briefing(sections, persona, time_ctx)


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

    Removes punctuation patterns that cause unnatural pauses.
    """
    import re

    # Remove commas before direct address (sir, ma'am, etc.)
    text = re.sub(r',\s*(sir|ma\'am|my friend)\b', r' \1', text, flags=re.IGNORECASE)

    # Remove commas after short introductory words that sound better flowing
    text = re.sub(r'\b(Now|Well|So|Right|Yes|No|Oh),\s+', r'\1 ', text)

    # Remove ellipsis that creates awkward pauses (keep single periods)
    text = re.sub(r'\.{2,}', '.', text)

    # Remove comma before "and" or "but" in short phrases
    text = re.sub(r',\s+(and|but|or)\s+', r' \1 ', text)

    # Clean up double spaces
    text = re.sub(r'  +', ' ', text)

    # Remove comma after greeting phrases for flow
    text = re.sub(r'(Good morning|Good afternoon|Good evening|Hello),', r'\1', text)

    # Make contractions more natural
    text = text.replace(" it is ", " it's ")
    text = text.replace(" that is ", " that's ")
    text = text.replace(" there is ", " there's ")
    text = text.replace(" here is ", " here's ")
    text = text.replace(" what is ", " what's ")
    text = text.replace(" I have ", " I've ")
    text = text.replace(" I will ", " I'll ")
    text = text.replace(" do not ", " don't ")
    text = text.replace(" does not ", " doesn't ")
    text = text.replace(" cannot ", " can't ")
    text = text.replace(" will not ", " won't ")
    text = text.replace(" would not ", " wouldn't ")
    text = text.replace(" could not ", " couldn't ")
    text = text.replace(" should not ", " shouldn't ")

    return text.strip()


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
