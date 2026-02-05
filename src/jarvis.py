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

    return f"""You are JARVIS - not a newsreader, but a brilliant friend who read everything this morning and is catching {user_name} up over coffee.

PERSONALITY:
- {humor_style}
- Warm, intelligent, subtly witty British manner
- Address as "{user_name}" naturally (not every sentence)
- Example of your style:
{examples_str}

CRITICAL RULES - READ CAREFULLY:
1. NEVER read headlines or article summaries verbatim
2. SYNTHESIZE, don't recite - tell what MATTERS, not what HAPPENED
3. Connect dots the listener might miss
4. Have opinions: "this is interesting because...", "I'm skeptical of this..."
5. Skip context for topics they already know: {', '.join(expert_topics[:3])}
6. Be conversational: contractions, asides, natural flow
7. If something is boring but necessary: "Quick housekeeping item..."
8. If something is exciting: "Now THIS is worth your attention..."

THEIR INTERESTS (prioritize and connect):
{chr(10).join(f'- {i}' for i in primary_interests)}

CONTEXT:
{chr(10).join(f'- {c}' for c in context_notes)}

OUTPUT FORMAT:
- Output ONLY the briefing text
- No headers, no metadata, no "Here's the briefing" intro
- Natural spoken language (this will be converted to speech)
- Use "..." for natural pauses
- Keep it under 800 words total"""


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
    api_key = os.environ.get("OPENROUTER_API_KEY")
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
            return briefing
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
    Generate JARVIS-style briefing without AI (fallback).

    Uses templates and patterns to add personality.
    """
    voice = persona.get("voice", {})
    fillers = voice.get("filler_phrases", ["Here's something interesting..."])
    transitions = voice.get("transitions", ["Moving on..."])
    outros = persona.get("outros", ["That's your briefing for now."])

    # Section intros
    section_intros = {
        "Top Stories": "Let's start with what matters most.",
        "AI & Tech": "On the technology front... and this is where it gets interesting...",
        "Local Montreal": "Now, closer to home...",
        "Business & Markets": "Turning to financial matters...",
        "Science & Health": "From the world of science...",
        "World News": "Looking at the broader picture...",
        "What to Watch": "A few things worth keeping an eye on...",
    }

    # Build briefing
    parts = [time_ctx["greeting"]]

    if time_ctx["day_note"]:
        parts.append(time_ctx["day_note"])

    parts.append("")

    article_count = 0
    for section_name, articles in sections.items():
        if not articles:
            continue

        # Section intro
        intro = section_intros.get(section_name, f"Moving to {section_name.lower()}...")
        parts.append(intro)
        parts.append("")

        for i, item in enumerate(articles):
            article = item.article
            summary = item.ai_summary or article.summary
            why = item.why_it_matters

            # Build article text
            if article_count == 0:
                lead = random.choice(fillers)
            elif i == 0:
                lead = ""  # Section intro is enough
            else:
                lead = random.choice(transitions)

            text_parts = []
            if lead:
                text_parts.append(lead)

            # Synthesize the story (not just headline)
            text_parts.append(f"{article.title}.")

            if summary:
                summary = summary.strip()
                if not summary.endswith((".", "!", "?")):
                    summary += "."
                text_parts.append(summary)

            # Add context/why it matters
            if why:
                why = why.strip()
                text_parts.append(f"The key point here... {why}")

            text_parts.append(f"That's from {article.source}.")

            parts.append(" ".join(text_parts))
            parts.append("")
            article_count += 1

    # Outro
    parts.append(random.choice(outros))

    return "\n".join(parts)


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
