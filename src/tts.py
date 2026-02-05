"""Text-to-Speech generation for news briefings.

Uses XTTS v2 for high-quality British voice synthesis.
Falls back to edge-tts if XTTS unavailable.
"""

import asyncio
from pathlib import Path

from .curator import CuratedArticle
from .jarvis import generate_jarvis_briefing


def generate_audio_brief(
    sections: dict[str, list[CuratedArticle]],
    output_dir: str = "audio",
    use_xtts: bool = False,  # Disabled - edge-tts sounds more natural
) -> str | None:
    """
    Generate JARVIS-style audio briefing from curated articles.

    Uses AI to create personalized, intelligent briefings with personality,
    then converts to speech using XTTS v2.

    Args:
        sections: Dict of section name to curated articles
        output_dir: Directory to save audio files
        use_xtts: Whether to use XTTS (True) or edge-tts fallback (False)

    Returns:
        Path to audio file relative to project root, or None if failed.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate the JARVIS briefing text
    print("Generating JARVIS-style briefing...")
    briefing = generate_jarvis_briefing(sections)

    if not briefing.strip():
        print("  [WARN] No briefing text generated")
        return None

    # Generate audio
    wav_path = output_path / "brief-en.wav"
    mp3_path = output_path / "brief-en.mp3"

    success = False

    if use_xtts:
        print("Converting to speech with XTTS v2...")
        success = _generate_xtts(briefing, str(wav_path))

    if not success:
        print("Converting to speech with edge-tts fallback...")
        success = asyncio.run(_generate_edge_tts(briefing, str(wav_path)))

    if not success:
        print("  [WARN] Speech generation failed")
        return None

    # Post-process audio
    print("Post-processing audio...")
    from .audio_processor import process_audio, get_audio_info

    if not process_audio(str(wav_path), str(mp3_path)):
        # Try direct copy if processing fails
        import shutil
        shutil.copy(wav_path, mp3_path.with_suffix('.wav'))
        mp3_path = mp3_path.with_suffix('.wav')

    # Clean up WAV if MP3 exists
    if mp3_path.exists() and wav_path.exists():
        wav_path.unlink()

    # Log info
    info = get_audio_info(str(mp3_path))
    if info:
        print(f"  Audio: {info['duration_str']} ({info['size_kb']:.0f} KB)")

    return f"audio/{mp3_path.name}"


def _generate_xtts(text: str, output_path: str) -> bool:
    """Generate speech using XTTS v2."""
    try:
        from .tts_xtts import generate_xtts
        return generate_xtts(text, output_path)
    except ImportError as e:
        print(f"  [WARN] XTTS not available: {e}")
        return False
    except Exception as e:
        print(f"  [WARN] XTTS error: {e}")
        return False


async def _generate_edge_tts(text: str, output_path: str) -> bool:
    """Generate speech using edge-tts (Microsoft Azure neural voices).

    These are high-quality neural voices that sound very natural.
    """
    try:
        import edge_tts
    except ImportError:
        print("  [WARN] edge-tts not installed")
        return False

    # British male voice - natural, warm, professional
    # RyanNeural = friendly/casual, ThomasNeural = slightly more formal
    voice = "en-GB-RyanNeural"

    # Natural rate, slight pitch adjustment for warmth without heaviness
    rate = "+0%"  # Normal speed
    pitch = "+0Hz"  # Natural pitch

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        print(f"  Generated {output_path} (edge-tts: {voice})")
        return True
    except Exception as e:
        print(f"  [WARN] edge-tts error: {e}")
        return False


if __name__ == "__main__":
    # Test
    from .fetcher import Article
    from datetime import datetime, timezone

    test_article = Article(
        title="OpenAI announces new model",
        link="https://example.com",
        summary="OpenAI has announced a new language model with improved reasoning capabilities.",
        source="TechCrunch",
        published=datetime.now(timezone.utc),
        category="tech_ai",
        language="en",
        reliability=0.8,
    )

    test_curated = CuratedArticle(
        article=test_article,
        score=0.9,
        ai_summary="OpenAI unveiled a new AI model today with significantly improved reasoning.",
        why_it_matters="This could change how developers build AI applications.",
    )

    sections = {"Top Stories": [test_curated]}
    result = generate_audio_brief(sections)
    print(f"Result: {result}")
