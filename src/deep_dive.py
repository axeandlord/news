"""Deep dive analytical briefing pipeline.

Generates per-topic deep analytical podcasts (~12 min each).
5-pass pipeline: Query Gen -> Research -> Synthesis -> Script -> Quality Check.
"""

import os
import re
import subprocess
from pathlib import Path

import httpx
import yaml

from .curator import CuratedArticle
from .jarvis import (
    BriefingSegment,
    _call_ollama,
    _check_ollama,
    _try_openrouter,
    prepare_for_tts,
    clean_summary,
    load_persona,
    SCRIPT_MODEL,
)
from .researcher import NewsResearcher, format_research_context
from .database import record_deep_dive


def load_deep_dive_config(config_path: str = "config/deep_dive.yaml") -> dict:
    """Load deep dive configuration."""
    path = Path(config_path)
    if not path.exists():
        return {"deep_dive": {"enabled": False}}
    with open(path) as f:
        return yaml.safe_load(f) or {"deep_dive": {"enabled": False}}


def select_deep_dive_topics(
    sections: dict[str, list[CuratedArticle]],
    config: dict,
) -> list[dict]:
    """Pick 1-2 topics for deep dives based on article density and score.

    Returns list of dicts with topic config + articles for each selected topic.
    """
    dd_config = config.get("deep_dive", {})
    if not dd_config.get("enabled", False):
        return []

    max_per_run = dd_config.get("max_per_run", 2)
    min_threshold = dd_config.get("min_articles_threshold", 4)
    topics = dd_config.get("topics", [])

    # Flatten all articles by category
    articles_by_category = {}
    for section_name, articles in sections.items():
        for a in articles:
            cat = a.article.category
            if cat not in articles_by_category:
                articles_by_category[cat] = []
            articles_by_category[cat].append(a)

    candidates = []
    for topic_config in topics:
        category = topic_config["category"]
        articles = articles_by_category.get(category, [])

        if len(articles) < min_threshold:
            continue

        avg_score = sum(a.score for a in articles) / len(articles) if articles else 0
        composite = len(articles) * avg_score

        candidates.append({
            "config": topic_config,
            "articles": articles,
            "composite_score": composite,
        })

    # Sort by composite score, take top max_per_run
    candidates.sort(key=lambda x: x["composite_score"], reverse=True)
    selected = candidates[:max_per_run]

    if selected:
        names = [s["config"]["name"] for s in selected]
        print(f"  Selected deep dive topics: {', '.join(names)}")

    return selected


def generate_deep_dive(
    topic: dict,
    researcher: NewsResearcher,
    persona_path: str = "config/persona.yaml",
) -> list[BriefingSegment]:
    """Generate a complete deep dive for one topic.

    5-pass pipeline:
      1. Ollama generates research queries from article clusters
      2. Tavily executes queries (advanced depth)
      3. Ollama synthesizes research into structured brief
      4. Claude Sonnet writes analytical script with [SECTION:] markers
      5. Split into segments
    """
    topic_config = topic["config"]
    articles = topic["articles"]
    topic_name = topic_config["name"]
    category = topic_config["category"]
    analysis_lens = topic_config.get("analysis_lens", "")

    print(f"\n  === Deep Dive: {topic_name} ({len(articles)} articles) ===")

    # === Pass 1: Research ===
    print(f"  Pass 1: Researching {topic_name}...")
    research_results = researcher.research_topic_deep(
        articles, category, analysis_lens
    )

    research_text = format_research_context(research_results, max_items=8)
    research_queries = list({r.query for r in research_results})

    # Record in DB
    record_deep_dive(topic_name, category, research_queries)

    # === Pass 2: Synthesis (Ollama) ===
    print(f"  Pass 2: Synthesizing research...")
    synthesis = _synthesize_research(articles, research_text, topic_name, analysis_lens)

    # === Pass 3: Script (Claude Sonnet) ===
    print(f"  Pass 3: Writing deep dive script...")
    persona = load_persona(persona_path)
    user_name = persona.get("user", {}).get("name", "sir")

    system_prompt = _build_deep_dive_system_prompt(
        topic_name, analysis_lens, persona
    )
    user_prompt = _build_deep_dive_user_prompt(
        articles, synthesis, research_text, topic_name
    )

    script = None
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_MAIN")
    if not api_key:
        try:
            api_key = subprocess.check_output(
                ["vault-export", "--get", "openrouter_main"], text=True, timeout=5
            ).strip() or None
        except Exception:
            api_key = None

    if api_key:
        script = _try_openrouter(system_prompt, user_prompt, api_key, model=SCRIPT_MODEL)
        if script:
            print(f"    Script generated ({len(script)} chars)")

    if not script:
        # Fallback to Ollama
        if _check_ollama():
            print("    Falling back to Ollama for script...")
            script = _call_ollama(
                user_prompt, system_prompt=system_prompt,
                max_tokens=8000, temperature=0.7
            )

    if not script:
        print(f"  [WARN] Failed to generate deep dive script for {topic_name}")
        return []

    # === Pass 4: Split into segments ===
    segments = _split_deep_dive_script(script, category, articles)
    print(f"  Split into {len(segments)} segments")

    return segments


def _synthesize_research(
    articles: list[CuratedArticle],
    research_text: str,
    topic_name: str,
    analysis_lens: str,
) -> str:
    """Ollama pass: synthesize articles + research into structured brief."""
    article_summaries = "\n".join(
        f"- {a.article.title} ({a.article.source}): {clean_summary(a.ai_summary or a.article.summary or '')[:200]}"
        for a in articles[:10]
    )

    prompt = f"""You are an analyst preparing a structured brief on {topic_name}.

TODAY'S STORIES:
{article_summaries}

BACKGROUND RESEARCH:
{research_text[:3000] if research_text else "No additional research available."}

ANALYSIS FOCUS:
{analysis_lens}

Create a structured analytical brief:

THESIS: [One paragraph: the central argument or narrative thread connecting these stories]
KEY EVIDENCE: [3-5 specific data points, quotes, or facts from the stories and research]
STAKEHOLDERS: [Who benefits, who loses, who should be paying attention]
EXPERT VIEWS: [Any analyst perspectives, competing viewpoints, or consensus positions from research]
OUTLOOK: [What happens next, key indicators to watch, scenario planning]

Be specific. Use numbers. Cite sources. No vague generalizations."""

    result = _call_ollama(prompt, max_tokens=2000, temperature=0.4)
    if result:
        return result

    # Fallback: return article summaries
    return article_summaries


def _build_deep_dive_system_prompt(
    topic_name: str, analysis_lens: str, persona: dict
) -> str:
    """Build the Claude system prompt for deep dive scripts."""
    user_name = persona.get("user", {}).get("name", "sir")
    humor = persona.get("humor", {})
    humor_style = humor.get("style", "dry british wit")
    expert_topics = persona.get("interests", {}).get("expert_level", [])

    return f"""You are writing a 12-15 minute DEEP DIVE PODCAST SCRIPT on {topic_name}. This is NOT a news recap. This is analytical journalism. Think Bloomberg Surveillance meets a brilliant friend who spent all morning reading analyst reports.

PERSONA: Same warm British-wit voice as the daily briefing, but in serious analyst mode. You did the research and you're explaining what it all means to {user_name}.

Humor style: {humor_style} (used sparingly -- this is the serious segment)

{user_name} knows: {', '.join(expert_topics[:4]) if expert_topics else 'AI, tech, LLMs'} -- skip basic explanations, go deeper than you normally would.

STRUCTURE (use these exact section markers):
[SECTION: The Setup] (~2 min) -- Hook with a striking data point or question. Frame the central narrative.
[SECTION: The Evidence] (~4 min) -- Walk through the evidence. Specific numbers, quotes, source attribution.
[SECTION: The Analysis] (~4 min) -- What it means. Who wins, who loses. Second-order effects. Where experts disagree.
[SECTION: The Outlook] (~2 min) -- Scenario planning. Leading indicators to watch. One actionable insight.

{analysis_lens}

CRITICAL RULES:
- Every claim needs attribution: "According to Bloomberg" or "The FT reports" or "Analysts at Goldman see"
- Specific numbers not vague: "revenue grew forty two percent" not "revenue grew significantly"
- When experts disagree, present both: "Goldman sees X but Morgan Stanley argues Y"
- Do NOT summarize articles in sequence. SYNTHESIZE across sources into a coherent narrative
- ZERO SYMBOLS: no hashtags, asterisks, bullets, dashes, percent signs, dollar signs
- Write ALL numbers as words: "fifty million dollars" not "$50M"
- Use contractions always: it's, they've, that's, won't, can't
- Smooth transitions only. This should flow like a conversation.

OUTPUT: Pure spoken text with [SECTION: Name] markers. No other formatting."""


def _build_deep_dive_user_prompt(
    articles: list[CuratedArticle],
    synthesis: str,
    research_text: str,
    topic_name: str,
) -> str:
    """Build the Claude user prompt for deep dive scripts."""
    from datetime import datetime
    date_str = datetime.now().strftime("%A, %B %-d, %Y")

    article_data = []
    for a in articles[:10]:
        summary = clean_summary(a.ai_summary or a.article.summary or "")
        why = clean_summary(a.why_it_matters or "")
        entry = f"TITLE: {a.article.title}\nSOURCE: {a.article.source}\nSUMMARY: {summary}"
        if why:
            entry += f"\nSIGNIFICANCE: {why}"
        article_data.append(entry)

    articles_text = "\n---\n".join(article_data)

    return f"""Today is {date_str}. Write a deep dive on {topic_name}.

TODAY'S STORIES:
{articles_text}

ANALYST SYNTHESIS:
{synthesis[:3000]}

BACKGROUND RESEARCH:
{research_text[:2000] if research_text else "No additional background research."}

Write a 12-15 minute analytical deep dive script. Start with a hook, not a greeting (the daily briefing already greeted the listener). Synthesize across all sources into a coherent analytical narrative. End with one actionable insight or indicator to watch.

Remember: pure spoken text only, no symbols, no formatting. Insert [SECTION: The Setup], [SECTION: The Evidence], [SECTION: The Analysis], [SECTION: The Outlook] markers."""


def _split_deep_dive_script(
    script: str,
    category: str,
    articles: list[CuratedArticle],
) -> list[BriefingSegment]:
    """Split a deep dive script into BriefingSegments."""
    all_hashes = [a.article.article_hash for a in articles]

    parts = re.split(r'\[SECTION:\s*([^\]]+)\]', script)

    if len(parts) < 3:
        return [BriefingSegment(
            section_name=f"Deep Dive",
            text=prepare_for_tts(script.strip()),
            article_hashes=all_hashes,
            segment_index=0,
        )]

    segments = []
    idx = 0

    # Handle preamble
    preamble = parts[0].strip()
    if preamble:
        segments.append(BriefingSegment(
            section_name="The Setup",
            text=prepare_for_tts(preamble),
            article_hashes=all_hashes,
            segment_index=idx,
        ))
        idx += 1

    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not text:
            continue

        segments.append(BriefingSegment(
            section_name=name,
            text=prepare_for_tts(text),
            article_hashes=all_hashes,
            segment_index=idx,
        ))
        idx += 1

    return segments
