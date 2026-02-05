# Quality Overhaul: Sources, Pipeline, and Script

**Date**: 2026-02-05
**Status**: Approved

## Problem

1. Briefing script is shallow, headline-like, no analysis depth
2. Stories treated as isolated - no connections or narrative arc
3. Poor article selection (RSS snippets are often garbage)
4. Awkward AI phrasing in script
5. Geopolitics sources need expansion

## Solution: Approach A + Cross-Referencing

### 1. Enhanced Source Layer

Add 8 geopolitics sources to feeds.yaml:

| Source | Feed URL | Reliability |
|--------|----------|-------------|
| War on the Rocks | warontherocks.com/feed | 0.90 |
| CSIS | csis.org/rss | 0.92 |
| Brookings Institution | brookings.edu/feed | 0.90 |
| Council on Foreign Relations | cfr.org/rss | 0.92 |
| The Diplomat | thediplomat.com/feed | 0.88 |
| Defense One | defenseone.com/rss | 0.85 |
| The War Zone | thedrive.com/the-war-zone/feed | 0.82 |
| Lawfare Blog | lawfaremedia.org/feed | 0.90 |

Full article extraction via `trafilatura` instead of relying on RSS summaries.

### 2. Two-Pass AI Pipeline with Cross-Referencing

```
[1] Full article text (trafilatura)
         |
[2] Per-article summary (local Ollama qwen2.5:14b) - FREE
         |
[3] Cross-reference pass (local Ollama) - FREE
    Groups stories, identifies threads, flags contradictions
         |
[4] Briefing script (Claude Sonnet via OpenRouter) - ~$0.03-0.05
    Receives summaries + cross-reference map + persona config
```

### 3. Improved Curation Scoring

New signals:
- Article length: +0.1 if >500 words
- Has quotes/data: +0.1
- Cross-source coverage: +0.15 if 3+ sources
- Steeper recency: +0.15 if <3h, +0.1 if <6h, +0.05 if <12h
- Clickbait penalty: -0.15
- Extraction failure penalty: -0.2

Geopolitics category weight: 1.0 -> 1.4
Geopolitics target articles: 8 -> 10

### 4. Briefing Script Prompt

Narrative structure:
1. Personalized greeting (time-aware, from persona.yaml)
2. Cold open with most compelling story
3. 3-4 section blocks (~3-4 min each), lead with strongest story
4. Cross-story connections woven throughout
5. Closing forward-looking thought

Depth requirements:
- Top 5 stories: WHY, WHO benefits/loses, WHAT next
- Remaining: 2-3 sentences with one insight
- Source disagreements called out explicitly

Voice: knowledgeable colleague, dry wit, contractions, no TTS-breaking symbols.

### 5. Files to Modify

| File | Changes |
|------|---------|
| config/feeds.yaml | +8 geopolitics sources |
| config/curation.yaml | Geopolitics weight 1.4, target 10, new scoring params |
| src/fetcher.py | Add trafilatura full article extraction |
| src/curator.py | Content-quality scoring, negative signals |
| src/jarvis.py | Two-pass pipeline, cross-referencing, new Sonnet prompt |
| requirements.txt | Add trafilatura |

### 6. Cost & Performance

- Cost: ~$0.03-0.05/run for Sonnet (everything else free)
- Time: ~3.5 min total (up from ~3 min)
- New dependency: trafilatura (~2MB)
