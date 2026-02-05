# BRIEF: Enterprise Polish Redesign

**Date:** 2026-02-04
**Status:** Approved for implementation

## Overview

Transform the news aggregator into "BRIEF" - an investor-ready personal AI news assistant with JARVIS-inspired personality, audio-first experience, and professional polish.

## Product Positioning

**Value Proposition:** "Your AI news concierge" - a personal assistant that reads you trustworthy news, tailored to what actually matters to you.

**Key Differentiators:**
1. Deep personalization - AI that truly learns your interests
2. Audio-first experience - JARVIS voice briefing as the core product
3. Source quality/transparency - Reliability scoring, no clickbait, multi-source verification

## Brand Identity

**Name:** BRIEF (with JARVIS as the AI personality)

**Color Palette:**
- Primary background: #0d0d0f (deep charcoal)
- Surface/cards: #161618 (subtle lift)
- Accent: #d4a574 (warm amber/gold)
- Text: #e8e6e3 (body), #f5f5f5 (headlines)
- Trust indicators: #5a9a8a (muted teal for high reliability)

**Typography:**
- Headlines: Inter or SF Pro Display
- Body: System font stack
- JARVIS personality text: Subtle amber accent or italic

**Visual Motifs:**
- Subtle radial gradient behind audio player
- Thin amber accent lines as dividers
- Sophisticated rounded corners
- Minimal iconography

## UI Structure

### Hero Section (60-70% viewport)

```
┌─────────────────────────────────────────────────────────┐
│  BRIEF                              [About] [Archive]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│         Good morning.                                   │
│         Your briefing is ready.                         │
│                                                         │
│              ┌─────────────────────┐                    │
│              │   ▁▃▅▇▅▃▁▃▅▇▅▃▁    │                    │
│              └─────────────────────┘                    │
│                                                         │
│              [ ▶  Play Briefing ]                       │
│                                                         │
│         Tuesday, February 4 · 11 stories · 4 min        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  ▼ Explore today's stories                              │
└─────────────────────────────────────────────────────────┘
```

- Time-aware greeting (morning/afternoon/evening)
- Waveform visualization animates during playback
- Play button transforms to pause with smooth animation
- Playback speed control (0.75x, 1x, 1.25x, 1.5x)
- Skip forward/back 15 seconds

### Sticky Player (when scrolling)

```
┌─────────────────────────────────────────────────────────┐
│  BRIEF   ▁▃▅▇▅▃▁  ▶  1:24 / 4:12    [1x ▾]    ━━●━━━━  │
└─────────────────────────────────────────────────────────┘
```

48px height, mini waveform, play/pause, time, speed, progress scrubber.

### Article Cards

```
┌────────────────────────────────────────────────────────┐
│  ┌──────┐                                              │
│  │ 92%  │  TechCrunch                     2 hours ago  │
│  └──────┘                                              │
│                                                        │
│  Google's Gemini app surpasses 750M monthly users      │
│                                                        │
│  Google revealed a significant milestone for its       │
│  Gemini app, announcing over 750 million monthly...    │
│                                                        │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 💡 Positions Google as the MAU leader in AI     │   │
│  │    assistants, ahead of ChatGPT's estimates.    │   │
│  └─────────────────────────────────────────────────┘   │
│                                                        │
│  [Read full article →]                                 │
└────────────────────────────────────────────────────────┘
```

- Reliability badge: circular progress indicator
- "Why it matters" callout with amber left border
- Currently-spoken article gets amber glow during playback

### Mobile Layout

- Large centered play button (thumb-friendly)
- Cards stack full width
- Slim sticky player (40px)
- Bottom sheet for speed control

## Voice & Audio

### Technology: XTTS v2 (Local, RTX 4080)

- Model: ~6GB VRAM
- Generation: ~10-15x realtime (4-min audio in 20-30 sec)
- Quality: 24kHz output
- Voice: Built-in British male speaker, JARVIS-style

### Audio Post-Processing Pipeline

```
XTTS Output (24kHz WAV)
    │
    ▼
1. Normalize to -1dB peak
2. Light compression (3:1 ratio)
3. High-pass filter (80Hz)
4. Subtle warmth EQ (+2dB 200Hz)
5. Export 192kbps MP3
```

## JARVIS Personality

### Core Principle

NOT a newsreader - a brilliant friend who read everything and is catching you up.

### System Prompt

```
You are JARVIS - not a newsreader, but a brilliant friend who read everything
this morning and is now catching me up over coffee.

CRITICAL RULES:
- Never read headlines or summaries verbatim
- Synthesize, don't recite
- Tell me what MATTERS about each story, not what HAPPENED
- Connect dots I might miss
- Have opinions - "this is interesting because..." / "I'm skeptical of this..."
- Skip context I already know (I follow AI closely, don't explain what GPT is)
- Be conversational: contractions, asides, natural flow
- If something is boring but necessary, acknowledge it: "Quick housekeeping item..."
- If something is exciting, show it: "Now THIS is worth your attention..."

You're briefing a friend who's smart but busy. Respect their time and intelligence.
```

### Personalization Config (config/persona.yaml)

```yaml
user:
  name: "sir"
  wake_time: "07:00"

interests:
  primary:
    - AI/ML developments (especially Claude, Anthropic)
    - Montreal local news
    - Tech startups and VC

humor:
  style: "dry british wit, understated sarcasm"
  examples:
    - "When AI companies fight: 'The machines are squabbling again.'"

voice:
  formality: "warm but professional"
  contractions: true
```

## Trust & Credibility

### About Page

Explains:
1. Sources - 20+ vetted sources with reliability scores
2. Curation - AI scoring, cross-referencing, deduplication
3. Briefing - Personalized synthesis, no fluff

### Footer

```
Curated from 20+ sources · Reliability-scored · Ad-free

How it works · Sources · Archive
```

## Technical Implementation

### New Files

```
src/
├── tts_xtts.py          # XTTS v2 integration
├── audio_processor.py   # FFmpeg post-processing
config/
├── persona.yaml         # JARVIS personalization
static/
├── css/brief.css        # Design system
├── js/player.js         # Audio player + waveform
templates/
├── index.html           # Redesigned template
├── about.html           # Trust/methodology
```

### Modified Files

```
src/
├── jarvis.py            # Enhanced prompts, persona integration
├── generator.py         # Uses new template
├── tts.py               # Routes to XTTS
├── main.py              # Audio processing step
```

### Dependencies

```
TTS                      # Coqui XTTS v2
torch                    # For XTTS
```

### Build Pipeline

1. Fetch feeds (unchanged)
2. Curate articles (unchanged)
3. Generate JARVIS text (enhanced)
4. XTTS generation (new - local GPU)
5. Audio post-process (new - ffmpeg)
6. Generate HTML (new template)
7. Archive (unchanged)
