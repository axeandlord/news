"""JARVIS-style news briefing generator.

Transforms raw news into personalized, conversational briefings.
NOT a newsreader - a brilliant friend who synthesizes what matters.

Pipeline:
  1. Per-article summaries (Ollama - free, local)
  2. Cross-reference pass (Ollama - finds story clusters & threads)
  3. Final briefing script (Claude Sonnet via OpenRouter - quality)
  4. Fallback: Ollama for script, then template
"""

import os
import random
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from .curator import CuratedArticle


@dataclass
class BriefingSegment:
    """A single topic segment of the audio briefing."""
    section_name: str           # "AI & Technology"
    text: str                   # TTS-ready text
    article_hashes: list[str] = field(default_factory=list)
    segment_index: int = 0

# Local Ollama API (free, uses local GPU)
OLLAMA_API_URL = "http://localhost:11434/api/chat"
LOCAL_MODEL = "qwen2.5:14b"  # Fast and capable on RTX 4080
MAX_ARTICLES_FOR_AI = 30  # Limit for reasonable response time

# OpenRouter API for final script (Sonnet for quality)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
SCRIPT_MODEL = "anthropic/claude-sonnet-4.5"  # Latest Sonnet for final script quality


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


# ============================================================
# PASS 1: Per-article summaries (Ollama - free)
# ============================================================

def summarize_articles_ollama(
    sections: dict[str, list[CuratedArticle]],
) -> dict[str, list[CuratedArticle]]:
    """Generate concise summaries for each article using local Ollama.

    Uses full article text when available, falls back to RSS summary.
    Updates ai_summary and why_it_matters on each CuratedArticle.
    """
    print("  Pass 1: Summarizing articles with Ollama...")

    count = 0
    for section_name, articles in sections.items():
        for item in articles:
            article = item.article
            # Use full text if available, otherwise RSS summary
            content = article.full_text if hasattr(article, 'full_text') and article.full_text else article.summary
            if not content:
                continue

            prompt = f"""Summarize this news article in 3-4 concise sentences. Include key facts, numbers, and quotes if present. Then add one sentence on why this matters.

Title: {article.title}
Source: {article.source}
Content: {content[:2000]}

Respond in this exact format:
SUMMARY: [your 3-4 sentence summary]
WHY: [one sentence on broader significance]"""

            result = _call_ollama(prompt, max_tokens=400, temperature=0.3)
            if result:
                summary_match = re.search(r"SUMMARY:\s*(.+?)(?=WHY:|$)", result, re.DOTALL)
                why_match = re.search(r"WHY:\s*(.+)", result, re.DOTALL)
                if summary_match:
                    item.ai_summary = summary_match.group(1).strip()
                if why_match:
                    item.why_it_matters = why_match.group(1).strip()
                count += 1

    print(f"    Summarized {count} articles")
    return sections


# ============================================================
# PASS 2: Cross-reference (Ollama - finds story clusters)
# ============================================================

def cross_reference_stories(
    sections: dict[str, list[CuratedArticle]],
) -> str:
    """Identify related stories, thematic threads, and contradictions.

    Returns a cross-reference map as text for the final script generator.
    """
    print("  Pass 2: Cross-referencing stories with Ollama...")

    # Build a flat list of all story summaries with IDs
    story_list = []
    idx = 0
    for section_name, articles in sections.items():
        for item in articles:
            summary = item.ai_summary or item.article.summary or item.article.title
            story_list.append(f"[{idx}] ({section_name}) {item.article.title}: {summary[:200]}")
            idx += 1

    if len(story_list) < 3:
        return ""

    stories_text = "\n".join(story_list)

    prompt = f"""Analyze these news stories and find connections between them.

{stories_text}

Identify:
1. CLUSTERS: Groups of stories about the same event or topic (list the story numbers)
2. THREADS: Thematic threads that span multiple sections (e.g., "AI regulation" appearing in tech and geopolitics)
3. TENSIONS: Any contradictions or different perspectives between sources on the same topic

Be concise. Use story numbers to reference articles. Only include genuine connections, not forced ones.

Format:
CLUSTERS:
- [numbers]: brief description
THREADS:
- brief description connecting [numbers]
TENSIONS:
- [numbers]: what they disagree on"""

    result = _call_ollama(prompt, max_tokens=800, temperature=0.3)
    if result:
        print(f"    Found cross-references ({len(result)} chars)")
        return result

    print("    No cross-references generated")
    return ""


# ============================================================
# PASS 3: Final briefing script (Sonnet via OpenRouter)
# ============================================================

def build_script_prompt(
    sections: dict[str, list[CuratedArticle]],
    cross_refs: str,
    persona: dict,
    time_ctx: dict,
) -> tuple[str, str]:
    """Build the system and user prompts for the final script generation."""

    user_name = persona.get("user", {}).get("name", "sir")
    humor = persona.get("humor", {})
    humor_style = humor.get("style", "dry british wit")
    humor_examples = humor.get("examples", [])
    interests = persona.get("interests", {})
    expert_topics = interests.get("expert_level", [])
    context_notes = persona.get("context", [])

    examples_str = ""
    if humor_examples:
        examples_str = "\n".join(f"  - {ex}" for ex in random.sample(humor_examples, min(3, len(humor_examples))))

    system_prompt = f"""You are writing a 15-minute PODCAST SCRIPT for {user_name}. This will be read aloud by text-to-speech.

PERSONA: Smart, warm, dry British wit. Like a brilliant well-informed friend catching them up. You're not a news anchor, you're a thoughtful companion who reads everything and picks out what's genuinely interesting.

Humor style: {humor_style}
Example tone:
{examples_str}

NARRATIVE STRUCTURE:
1. Start with the personalized greeting provided, then immediately hook with the single most compelling story of the day
2. Flow through 3-4 thematic sections (3-4 minutes each), leading each with the strongest story
3. Connect related stories across sections: "This feeds directly into something happening in..." / "Remember that AI story? Well..."
4. Close with one forward-looking thought that ties the briefing together

DEPTH REQUIREMENTS:
- Top 5 stories: Explain WHY it matters, WHO benefits or loses, WHAT happens next
- Other stories: 2-3 sentences with one genuine insight
- When sources disagree, say so: "Reuters reports X, but Al Jazeera frames it as Y"
- {user_name} knows: {', '.join(expert_topics[:4]) if expert_topics else 'AI, tech, LLMs'} - skip basic explanations, go deeper

ABSOLUTE TTS RULES (text-to-speech will sound terrible otherwise):
- ZERO SYMBOLS: no hashtags, asterisks, bullets, dashes, percent signs, dollar signs
- ZERO STRUCTURE: no headers, no lists, no numbered items, no "firstly/secondly"
- Write ALL numbers as words: "fifty million dollars" not "$50M", "about thirty percent" not "30%"
- Use contractions always: it's, they've, that's, won't, can't
- Smooth transitions only: "Meanwhile", "Speaking of which", "Now here's where it gets interesting"

CONTEXT:
{chr(10).join(f"- {c}" for c in context_notes[:4]) if context_notes else "- Tech-savvy listener who appreciates depth over breadth"}

SECTION MARKERS (required for audio segmentation):
- Before each topic section, insert exactly [SECTION: Section Name] on its own line
- Use the section names from the story categories provided
- First section should be [SECTION: Introduction] (for greeting + hook)
- Last section should be [SECTION: Wrap-up] (for closing thoughts)

OUTPUT: Pure spoken text with section markers. No other formatting. No metadata. Just words that flow naturally when read aloud."""

    # Build structured news content
    stories_text = []
    for section_name, articles in sections.items():
        if not articles:
            continue
        section_stories = []
        for item in articles:
            article = item.article
            summary = clean_summary(item.ai_summary or article.summary or "")
            why = clean_summary(item.why_it_matters or "")
            title = clean_summary(article.title)
            source = article.source

            entry = f"TITLE: {title}\nSOURCE: {source}\nSUMMARY: {summary}"
            if why:
                entry += f"\nSIGNIFICANCE: {why}"
            section_stories.append(entry)

        stories_text.append(f"=== {section_name} ===\n" + "\n---\n".join(section_stories))

    all_stories = "\n\n".join(stories_text)

    # Cross-reference map
    cross_ref_section = ""
    if cross_refs:
        cross_ref_section = f"""

STORY CONNECTIONS (use these to weave a narrative, don't just list stories in order):
{cross_refs}
"""

    greeting = time_ctx.get("greeting", "Good morning sir.")
    day_note = time_ctx.get("day_note", "")
    greeting_section = greeting
    if day_note:
        greeting_section += f" {day_note}"

    user_prompt = f"""Today is {time_ctx['date_str']}.

GREETING TO START WITH: "{greeting_section}"

Here are today's stories:

{all_stories}
{cross_ref_section}

Now write a natural, flowing podcast script (about 15 minutes when read aloud). Start with the greeting above, then hook immediately with the most compelling story. Weave connections between stories where they exist. End with a brief, thoughtful wrap-up.

Remember: pure spoken text only, no symbols, no structure, no formatting. Write it exactly as you'd speak it to a smart friend. Insert [SECTION: Name] markers between topic sections."""

    return system_prompt, user_prompt


def split_script_into_segments(
    raw_script: str,
    sections: dict[str, list[CuratedArticle]],
) -> list[BriefingSegment]:
    """Split an AI-generated script into BriefingSegments using [SECTION: ...] markers.

    Falls back to a single segment if no markers found.
    """
    # Build a map of section name -> article hashes
    section_hashes = {}
    for section_name, articles in sections.items():
        section_hashes[section_name.lower()] = [
            a.article.article_hash for a in articles
        ]

    # Split on [SECTION: Name] markers
    parts = re.split(r'\[SECTION:\s*([^\]]+)\]', raw_script)

    # parts = [text_before_first_marker, name1, text1, name2, text2, ...]
    # If no markers found, parts has just one element
    if len(parts) < 3:
        # No markers - return single segment with all hashes
        all_hashes = []
        for hashes in section_hashes.values():
            all_hashes.extend(hashes)
        return [BriefingSegment(
            section_name="Full Briefing",
            text=prepare_for_tts(raw_script.strip()),
            article_hashes=all_hashes,
            segment_index=0,
        )]

    segments = []
    idx = 0

    # Handle any text before the first marker as intro
    preamble = parts[0].strip()
    if preamble:
        segments.append(BriefingSegment(
            section_name="Introduction",
            text=prepare_for_tts(preamble),
            article_hashes=[],
            segment_index=idx,
        ))
        idx += 1

    # Process marker/text pairs
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not text:
            continue

        # Match section name to article hashes (fuzzy, accumulate all matches)
        hashes = []
        name_lower = name.lower()
        for sec_name, sec_hashes in section_hashes.items():
            # Check substring match (either direction)
            if sec_name in name_lower or name_lower in sec_name:
                hashes.extend(sec_hashes)
                continue
            # Partial word match (any shared word)
            sec_words = set(sec_name.replace("&", "").split())
            name_words = set(name_lower.replace("&", "").split())
            if sec_words & name_words:
                hashes.extend(sec_hashes)
        # Deduplicate while preserving order
        seen = set()
        unique_hashes = []
        for h in hashes:
            if h not in seen:
                seen.add(h)
                unique_hashes.append(h)
        hashes = unique_hashes

        segments.append(BriefingSegment(
            section_name=name,
            text=prepare_for_tts(text),
            article_hashes=hashes,
            segment_index=idx,
        ))
        idx += 1

    return segments


def generate_jarvis_briefing(
    sections: dict[str, list[CuratedArticle]],
    persona_path: str = "config/persona.yaml",
) -> list[BriefingSegment]:
    """
    Generate a complete JARVIS-style news briefing using the multi-pass pipeline.

    Pipeline:
      1. Per-article summaries (Ollama - free)
      2. Cross-referencing (Ollama - free)
      3. Final script (Sonnet via OpenRouter - quality)
      Fallback: Ollama for script, then template
    """
    persona = load_persona(persona_path)
    time_ctx = get_time_context(persona)

    # Limit articles per section for reasonable AI processing
    limited_sections = {}
    total_for_ai = 0
    for section_name, articles in sections.items():
        remaining = MAX_ARTICLES_FOR_AI - total_for_ai
        if remaining <= 0:
            break
        take = min(len(articles), max(3, remaining // max(1, len(sections))))
        limited_sections[section_name] = articles[:take]
        total_for_ai += take

    # === PASS 1: Per-article summaries (Ollama, free) ===
    ollama_available = _check_ollama()
    if ollama_available:
        limited_sections = summarize_articles_ollama(limited_sections)
    else:
        print("  [WARN] Ollama unavailable, using RSS summaries")

    # === PASS 2: Cross-reference stories (Ollama, free) ===
    cross_refs = ""
    if ollama_available:
        cross_refs = cross_reference_stories(limited_sections)

    # === PASS 3: Final script (Sonnet via OpenRouter for quality) ===
    system_prompt, user_prompt = build_script_prompt(
        limited_sections, cross_refs, persona, time_ctx
    )

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_MAIN")
    if not api_key:
        # Load from vault if not in env (e.g., webhook started without vault-export)
        try:
            api_key = subprocess.check_output(
                ["vault-export", "--get", "openrouter_main"], text=True, timeout=5
            ).strip() or None
        except Exception:
            api_key = None

    # Try Sonnet first for best quality
    if api_key:
        print(f"  Calling OpenRouter ({SCRIPT_MODEL})...")
        briefing = _try_openrouter(system_prompt, user_prompt, api_key, model=SCRIPT_MODEL)
        if briefing:
            print(f"  Script generated with {SCRIPT_MODEL} ({len(briefing)} chars)")
            segments = split_script_into_segments(briefing, limited_sections)
            print(f"  Split into {len(segments)} segments")
            return segments
        print("  [WARN] OpenRouter failed, trying Ollama fallback")
    else:
        print("  [WARN] No OpenRouter API key found, using Ollama")

    # Fallback: Ollama for the script too (free but lower quality)
    if ollama_available:
        print("  Falling back to Ollama for script generation...")
        old_system = _build_ollama_script_prompt(persona, time_ctx)
        news_content = build_news_content(limited_sections)
        old_user = f"""It's {time_ctx['time_of_day'].replace('_', ' ')}.

Here's what happened today:

{news_content}

{"STORY CONNECTIONS: " + cross_refs if cross_refs else ""}

Write a natural podcast briefing about 12-15 minutes long. Start with the greeting: "{time_ctx.get('greeting', 'Good morning sir.')}"
Pure spoken text, no symbols, no formatting. Hook with the best story first. Connect related stories where natural. Insert [SECTION: Name] markers between topic sections."""

        briefing = _call_ollama(old_user, system_prompt=old_system, max_tokens=8000, temperature=0.7)
        if briefing:
            print(f"  Generated briefing with Ollama ({LOCAL_MODEL})")
            segments = split_script_into_segments(briefing, limited_sections)
            print(f"  Split into {len(segments)} segments")
            return segments

    # Final fallback to template
    print("  [WARN] AI unavailable, using template style")
    return _build_template_segments(sections, persona, time_ctx)


# ============================================================
# AI API helpers
# ============================================================

def _check_ollama() -> bool:
    """Check if Ollama is running and responsive."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _call_ollama(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 2000,
    temperature: float = 0.5,
) -> str | None:
    """Call local Ollama API."""
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = httpx.post(
            OLLAMA_API_URL,
            json={
                "model": LOCAL_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=600,
        )
        if response.status_code == 200:
            return response.json()["message"]["content"]
    except Exception as e:
        print(f"    [WARN] Ollama error: {e}")
    return None


def _try_openrouter(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = SCRIPT_MODEL,
) -> str | None:
    """Call OpenRouter API with specified model."""
    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://news.bezman.ca",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 8000,
                "temperature": 0.7,
            },
            timeout=180,
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            body = response.text[:200]
            print(f"  [WARN] OpenRouter error {response.status_code}: {body}")
    except Exception as e:
        print(f"  [WARN] OpenRouter error: {e}")
    return None


def _build_ollama_script_prompt(persona: dict, time_ctx: dict) -> str:
    """Build a simpler script prompt for Ollama fallback."""
    user_name = persona.get("user", {}).get("name", "sir")
    expert_topics = persona.get("interests", {}).get("expert_level", [])

    return f"""You are writing a PODCAST SCRIPT for {user_name} - this will be read aloud by text-to-speech.

YOUR VOICE: Smart, warm, British-friendly tone. Like a well-informed friend catching them up over coffee.

ABSOLUTE RULES (TTS will sound terrible otherwise):
1. ZERO SYMBOLS - no #, *, -, %, $, or any special characters
2. ZERO LISTS - no bullet points, no numbered items, no "firstly/secondly"
3. ZERO STRUCTURE - no headers, no sections, just flowing natural speech
4. Write numbers as words: "fifty million dollars" not "$50M", "about thirty percent" not "30%"
5. Use contractions: it's, they've, that's, won't, can't
6. Smooth transitions only: "Meanwhile", "Speaking of which", "On a related note"

WHAT MAKES IT GOOD:
- Explain WHY things matter, not just what happened
- Connect dots between related stories naturally
- {user_name} knows about: {', '.join(expert_topics[:3]) if expert_topics else 'AI, tech'} - skip basic explanations

SECTION MARKERS: Insert [SECTION: Section Name] on its own line before each topic section. Start with [SECTION: Introduction], end with [SECTION: Wrap-up].

OUTPUT: Pure spoken text with section markers. No other formatting. No metadata. Just words that sound natural when read aloud."""


# ============================================================
# Content building helpers
# ============================================================

def build_news_content(sections: dict[str, list[CuratedArticle]]) -> str:
    """Build news content as plain text for AI - no markdown, no metadata."""
    stories = []

    for section_name, articles in sections.items():
        if not articles:
            continue

        category = section_name.replace("&", "and")

        for item in articles:
            article = item.article
            summary = clean_summary(item.ai_summary or article.summary or "")
            title = clean_summary(article.title)
            source = article.source

            story = f"{category}: {title}. {summary} (from {source})"
            stories.append(story)

    return "\n\n".join(stories)


# ============================================================
# Template fallback (no AI needed)
# ============================================================

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
    first_section_intros = {
        "AI & Technology": ["Starting with tech.", "First up, AI and tech.", "On the tech front."],
        "Finance & Markets": ["Starting with markets.", "First, the financial picture.", "Let's start with finance."],
        "World & Geopolitics": ["Starting internationally.", "First, world news.", "On the global front."],
        "Montreal": ["Starting locally.", "First, here in Montreal.", "Closer to home first."],
        "Quebec": ["Starting with Quebec.", "First, provincial news."],
        "Canada": ["Starting nationally.", "First, across Canada."],
        "Wildcards & Emerging": ["Starting with some interesting developments.", "First, a few things worth noting."],
    }

    section_transitions = {
        "AI & Technology": ["Shifting to tech.", "Now for AI and tech.", "On the tech side.", "In the tech world."],
        "Finance & Markets": ["Turning to markets.", "Now for finance.", "On the money side.", "Financially speaking."],
        "World & Geopolitics": ["Looking internationally.", "On the world stage.", "Globally.", "Further afield."],
        "Montreal": ["Closer to home now.", "Here in Montreal.", "Locally.", "Back home."],
        "Quebec": ["In Quebec.", "Provincially.", "Around Quebec."],
        "Canada": ["Nationally.", "Across Canada.", "On the national scene."],
        "Wildcards & Emerging": ["A few other things.", "Some other developments.", "Also worth knowing."],
    }

    article_patterns = [
        "{title}. {summary} {source_attr}",
        "{source} is reporting that {summary_lower} {title_context}",
        "{summary} {source_attr} {title_context}",
        "{title}. {source_attr} {summary}",
    ]

    article_transitions = [
        "Also,", "And", "Meanwhile,", "Separately,", "Additionally,",
        "Related to that,", "On a similar note,", "In other news,",
        "", "", "",
    ]

    source_before = [
        "{source} is reporting that",
        "{source} says",
        "According to {source},",
        "Per {source},",
        "{source} has the story:",
    ]

    source_after = [
        "That's from {source}.",
        "Via {source}.",
        "That's according to {source}.",
        "This comes from {source}.",
        "{source} has the details.",
        "That's per {source}.",
    ]

    closings = [
        "That's the rundown.",
        "That covers the main points.",
        "That's what you need to know.",
        "And that's where things stand.",
        "That's your update.",
        "That's the latest.",
    ]

    # === BUILD THE BRIEFING ===
    used_article_trans = []
    used_source_after = []
    used_patterns = []

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

            text_parts = []

            if i > 0:
                available = [t for t in article_transitions if t not in used_article_trans[-2:]]
                trans = random.choice(available) if available else random.choice(article_transitions)
                used_article_trans.append(trans)
                if trans:
                    text_parts.append(trans)

            available_patterns = [p for p in article_patterns if p not in used_patterns[-2:]]
            pattern = random.choice(available_patterns) if available_patterns else random.choice(article_patterns)
            used_patterns.append(pattern)

            summary_clean = summary.strip().rstrip(".") if summary else ""
            if summary_clean and len(summary_clean) > 1:
                if summary_clean[1].islower():
                    summary_lower = summary_clean[0].lower() + summary_clean[1:]
                else:
                    summary_lower = summary_clean
            else:
                summary_lower = summary_clean
            title_context = f"The headline: {title}." if "title_context" in pattern and summary else ""

            available_src = [s for s in source_after if s not in used_source_after[-2:]]
            source_attr = random.choice(available_src).format(source=source)
            used_source_after.append(source_attr)

            if "{source} is reporting" in pattern or pattern.startswith("{source}"):
                src_before = random.choice(source_before).format(source=source)
                if summary_lower:
                    text_parts.append(f"{src_before} {summary_lower}.")
                else:
                    text_parts.append(f"{src_before} {title.lower()}.")
            elif pattern.startswith("{summary}"):
                if summary_clean:
                    text_parts.append(f"{summary_clean}. {source_attr}")
                else:
                    text_parts.append(f"{title}. {source_attr}")
            else:
                text_parts.append(f"{title}.")
                if summary_clean:
                    text_parts.append(f"{summary_clean}.")
                text_parts.append(source_attr)

            parts.append(" ".join(text_parts))
            total_articles += 1

        parts.append("")
        section_count += 1

    closing = random.choice(closings)
    parts.append(closing)

    return prepare_for_tts("\n".join(parts))


def _build_template_segments(
    sections: dict[str, list[CuratedArticle]],
    persona: dict,
    time_ctx: dict,
) -> list[BriefingSegment]:
    """Build segments from the template fallback, one per section."""
    # Use template to get full text, then split by section
    # We'll build segments directly for better control
    greetings = {
        "morning": "Good morning sir.",
        "morning_early": "Good morning sir.",
        "afternoon": "Good afternoon sir.",
        "evening": "Good evening sir.",
        "late_night": "Evening sir.",
    }

    openings = [
        "Here's what's going on.",
        "Let me catch you up.",
        "Here's what you need to know.",
    ]

    closings = [
        "That's the rundown.",
        "That covers the main points.",
        "That's what you need to know.",
    ]

    greeting = greetings.get(time_ctx.get("time_of_day", "evening"), "Hello sir.")
    opening = random.choice(openings)

    segments = []
    idx = 0

    # Introduction segment
    segments.append(BriefingSegment(
        section_name="Introduction",
        text=prepare_for_tts(f"{greeting} {opening}"),
        article_hashes=[],
        segment_index=idx,
    ))
    idx += 1

    # One segment per section
    for section_name, articles in sections.items():
        if not articles:
            continue

        parts = []
        for i, item in enumerate(articles):
            article = item.article
            summary = clean_summary(item.ai_summary or article.summary or "")
            title = clean_summary(article.title).rstrip(".").strip()
            source = article.source

            if summary:
                parts.append(f"{title}. {summary} That's from {source}.")
            else:
                parts.append(f"{title}. Via {source}.")

        hashes = [a.article.article_hash for a in articles]
        segments.append(BriefingSegment(
            section_name=section_name,
            text=prepare_for_tts(" ".join(parts)),
            article_hashes=hashes,
            segment_index=idx,
        ))
        idx += 1

    # Closing segment
    segments.append(BriefingSegment(
        section_name="Wrap-up",
        text=prepare_for_tts(random.choice(closings)),
        article_hashes=[],
        segment_index=idx,
    ))

    return segments


# ============================================================
# Text cleaning and TTS preparation
# ============================================================

def clean_summary(text: str) -> str:
    """
    Clean raw RSS/article summaries for human-friendly TTS.

    Strips academic jargon, arXiv IDs, metadata prefixes, etc.
    """
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
    # Remove markdown formatting completely
    text = re.sub(r'#{1,6}\s*', '', text)  # Headers
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # Bold/italic
    text = re.sub(r'`[^`]+`', '', text)  # Code
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links

    # Remove bullet points and list markers
    text = re.sub(r'^[\s]*[-\u2022*]\s+', '', text, flags=re.MULTILINE)
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
    text = text.replace('\u2026', '.')

    # Clean up quotes to simple ones
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")

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
    match = re.match(r'\$?([\d.]+)\s*([BMKbmk])?', money_str)
    if not match:
        return money_str

    num = float(match.group(1))
    suffix = (match.group(2) or '').upper()

    multipliers = {'B': 'billion', 'M': 'million', 'K': 'thousand'}
    mult_word = multipliers.get(suffix, '')

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
