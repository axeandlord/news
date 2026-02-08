"""Text-to-Speech generation for news briefings.

Generates per-segment MP3 files for playlist-mode playback,
plus a combined MP3 for backward compatibility.
Falls back to edge-tts (Microsoft Azure neural voices).
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from .curator import CuratedArticle
from .jarvis import generate_jarvis_briefing, BriefingSegment


def generate_audio_brief(
    sections: dict[str, list[CuratedArticle]],
    output_dir: str = "audio",
) -> tuple[str | None, list[BriefingSegment] | None, dict | None]:
    """
    Generate JARVIS-style audio briefing from curated articles.

    Generates per-segment MP3s + combined MP3 + segments metadata JSON.

    Returns:
        Tuple of (combined_audio_path, segments_list, segments_metadata)
        or (None, None, None) if failed.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate the JARVIS briefing segments
    print("Generating JARVIS-style briefing...")
    segments = generate_jarvis_briefing(sections)

    if not segments:
        print("  [WARN] No briefing segments generated")
        return None, None, None

    # Check we have actual text
    total_text = sum(len(s.text) for s in segments)
    if total_text < 10:
        print("  [WARN] Briefing segments have no text")
        return None, None, None

    # Generate per-segment audio
    print(f"  Generating audio for {len(segments)} segments...")
    from .audio_processor import process_audio, get_audio_info, get_audio_duration

    segment_mp3s = []
    segment_meta = []

    for seg in segments:
        if not seg.text.strip():
            continue

        wav_path = output_path / f"segment-en-{seg.segment_index}.wav"
        mp3_path = output_path / f"segment-en-{seg.segment_index}.mp3"

        # Generate TTS for this segment
        success = asyncio.run(_generate_edge_tts(seg.text, str(wav_path)))
        if not success:
            print(f"    [WARN] TTS failed for segment {seg.segment_index}: {seg.section_name}")
            continue

        # Post-process to MP3
        if not process_audio(str(wav_path), str(mp3_path)):
            import shutil
            shutil.copy(wav_path, mp3_path.with_suffix('.wav'))
            mp3_path = mp3_path.with_suffix('.wav')

        # Clean up WAV
        if mp3_path.exists() and wav_path.exists():
            wav_path.unlink()

        # Get duration
        duration = get_audio_duration(str(mp3_path))

        segment_mp3s.append(str(mp3_path))
        segment_meta.append({
            "index": seg.segment_index,
            "section": seg.section_name,
            "file": f"audio/{mp3_path.name}",
            "duration": round(duration, 1),
            "article_hashes": seg.article_hashes,
        })

        print(f"    Segment {seg.segment_index} ({seg.section_name}): {duration:.1f}s")

    if not segment_mp3s:
        print("  [WARN] No segment audio generated")
        return None, segments, None

    # Concatenate all segments into combined MP3
    combined_path = output_path / "brief-en.mp3"
    from .audio_processor import concatenate_segments
    if not concatenate_segments(segment_mp3s, str(combined_path)):
        # If concat fails, use first segment as fallback
        import shutil
        shutil.copy(segment_mp3s[0], combined_path)

    # Build and write segments metadata JSON
    segments_metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "segments": segment_meta,
    }
    meta_path = output_path / "segments-en.json"
    meta_path.write_text(json.dumps(segments_metadata, indent=2))

    # Log combined info
    info = get_audio_info(str(combined_path))
    if info:
        print(f"  Combined audio: {info['duration_str']} ({info['size_kb']:.0f} KB)")
    print(f"  Segments metadata: {meta_path}")

    return f"audio/{combined_path.name}", segments, segments_metadata


def generate_audio_brief_fr(
    sections: dict[str, list[CuratedArticle]],
    en_segments: list[BriefingSegment] | None = None,
    output_dir: str = "audio",
) -> tuple[str | None, dict | None]:
    """
    Generate French audio briefing by translating per-segment.

    Translates each segment individually (shorter = better quality),
    then generates per-segment French audio + combined.

    Returns:
        Tuple of (combined_audio_path, segments_metadata) or (None, None).
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if not en_segments:
        print("  [WARN] No English segments to translate")
        return None, None

    from .audio_processor import process_audio, get_audio_info, get_audio_duration, concatenate_segments

    segment_mp3s = []
    segment_meta = []

    for seg in en_segments:
        if not seg.text.strip():
            continue

        # Translate this segment
        fr_text = _translate_to_french(seg.text)
        if not fr_text:
            print(f"    [WARN] Translation failed for segment {seg.segment_index}")
            continue

        wav_path = output_path / f"segment-fr-{seg.segment_index}.wav"
        mp3_path = output_path / f"segment-fr-{seg.segment_index}.mp3"

        # Generate French TTS
        success = asyncio.run(_generate_edge_tts_fr(fr_text, str(wav_path)))
        if not success:
            continue

        # Post-process to MP3
        if not process_audio(str(wav_path), str(mp3_path)):
            import shutil
            shutil.copy(wav_path, mp3_path.with_suffix('.wav'))
            mp3_path = mp3_path.with_suffix('.wav')

        if mp3_path.exists() and wav_path.exists():
            wav_path.unlink()

        duration = get_audio_duration(str(mp3_path))
        segment_mp3s.append(str(mp3_path))
        segment_meta.append({
            "index": seg.segment_index,
            "section": seg.section_name,
            "file": f"audio/{mp3_path.name}",
            "duration": round(duration, 1),
            "article_hashes": seg.article_hashes,
        })

    if not segment_mp3s:
        print("  [WARN] No French segment audio generated")
        return None, None

    # Concatenate into combined French MP3
    combined_path = output_path / "brief-fr.mp3"
    if not concatenate_segments(segment_mp3s, str(combined_path)):
        import shutil
        shutil.copy(segment_mp3s[0], combined_path)

    # Write French segments metadata
    segments_metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "segments": segment_meta,
    }
    meta_path = output_path / "segments-fr.json"
    meta_path.write_text(json.dumps(segments_metadata, indent=2))

    info = get_audio_info(str(combined_path))
    if info:
        print(f"  French audio: {info['duration_str']} ({info['size_kb']:.0f} KB)")

    return f"audio/{combined_path.name}", segments_metadata


def generate_deep_dive_audio(
    category: str,
    segments: list[BriefingSegment],
    output_dir: str = "audio",
) -> tuple[str | None, dict | None]:
    """Generate audio for a deep dive topic.

    Same pattern as generate_audio_brief() but with dd-{category} file naming.

    Returns:
        Tuple of (combined_audio_path, segments_metadata) or (None, None).
    """
    if not segments:
        return None, None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    from .audio_processor import process_audio, get_audio_info, get_audio_duration, concatenate_segments

    segment_mp3s = []
    segment_meta = []

    for seg in segments:
        if not seg.text.strip():
            continue

        wav_path = output_path / f"dd-{category}-segment-en-{seg.segment_index}.wav"
        mp3_path = output_path / f"dd-{category}-segment-en-{seg.segment_index}.mp3"

        success = asyncio.run(_generate_edge_tts(seg.text, str(wav_path)))
        if not success:
            print(f"    [WARN] TTS failed for dd segment {seg.segment_index}: {seg.section_name}")
            continue

        if not process_audio(str(wav_path), str(mp3_path)):
            import shutil
            shutil.copy(wav_path, mp3_path.with_suffix('.wav'))
            mp3_path = mp3_path.with_suffix('.wav')

        if mp3_path.exists() and wav_path.exists():
            wav_path.unlink()

        duration = get_audio_duration(str(mp3_path))
        segment_mp3s.append(str(mp3_path))
        segment_meta.append({
            "index": seg.segment_index,
            "section": seg.section_name,
            "file": f"audio/{mp3_path.name}",
            "duration": round(duration, 1),
            "article_hashes": seg.article_hashes,
        })

        print(f"    DD Segment {seg.segment_index} ({seg.section_name}): {duration:.1f}s")

    if not segment_mp3s:
        return None, None

    # Concatenate into combined deep dive MP3
    combined_path = output_path / f"dd-{category}-en.mp3"
    if not concatenate_segments(segment_mp3s, str(combined_path)):
        import shutil
        shutil.copy(segment_mp3s[0], combined_path)

    segments_metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "segments": segment_meta,
    }
    meta_path = output_path / f"dd-{category}-segments-en.json"
    meta_path.write_text(json.dumps(segments_metadata, indent=2))

    info = get_audio_info(str(combined_path))
    if info:
        print(f"  DD {category} audio: {info['duration_str']} ({info['size_kb']:.0f} KB)")

    return f"audio/{combined_path.name}", segments_metadata


def generate_deep_dive_audio_fr(
    category: str,
    en_segments: list[BriefingSegment],
    output_dir: str = "audio",
) -> tuple[str | None, dict | None]:
    """Generate French audio for a deep dive by translating per-segment.

    Returns:
        Tuple of (combined_audio_path, segments_metadata) or (None, None).
    """
    if not en_segments:
        return None, None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    from .audio_processor import process_audio, get_audio_info, get_audio_duration, concatenate_segments

    segment_mp3s = []
    segment_meta = []

    for seg in en_segments:
        if not seg.text.strip():
            continue

        fr_text = _translate_to_french(seg.text)
        if not fr_text:
            continue

        wav_path = output_path / f"dd-{category}-segment-fr-{seg.segment_index}.wav"
        mp3_path = output_path / f"dd-{category}-segment-fr-{seg.segment_index}.mp3"

        success = asyncio.run(_generate_edge_tts_fr(fr_text, str(wav_path)))
        if not success:
            continue

        if not process_audio(str(wav_path), str(mp3_path)):
            import shutil
            shutil.copy(wav_path, mp3_path.with_suffix('.wav'))
            mp3_path = mp3_path.with_suffix('.wav')

        if mp3_path.exists() and wav_path.exists():
            wav_path.unlink()

        duration = get_audio_duration(str(mp3_path))
        segment_mp3s.append(str(mp3_path))
        segment_meta.append({
            "index": seg.segment_index,
            "section": seg.section_name,
            "file": f"audio/{mp3_path.name}",
            "duration": round(duration, 1),
            "article_hashes": seg.article_hashes,
        })

    if not segment_mp3s:
        return None, None

    combined_path = output_path / f"dd-{category}-fr.mp3"
    if not concatenate_segments(segment_mp3s, str(combined_path)):
        import shutil
        shutil.copy(segment_mp3s[0], combined_path)

    segments_metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "segments": segment_meta,
    }
    meta_path = output_path / f"dd-{category}-segments-fr.json"
    meta_path.write_text(json.dumps(segments_metadata, indent=2))

    info = get_audio_info(str(combined_path))
    if info:
        print(f"  DD {category} FR audio: {info['duration_str']} ({info['size_kb']:.0f} KB)")

    return f"audio/{combined_path.name}", segments_metadata


def _translate_to_french(text: str) -> str | None:
    """Translate English briefing text to French using Ollama."""
    try:
        import httpx
        response = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen2.5:14b",
                "messages": [
                    {"role": "system", "content": "You are a professional translator. Translate the following English podcast script to natural Quebec French. Keep the same casual, conversational tone. Replace 'sir' with 'monsieur'. Keep proper nouns (company names, people) unchanged. Output ONLY the French translation, no commentary."},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {"num_predict": 8000, "temperature": 0.3},
            },
            timeout=600,
        )
        if response.status_code == 200:
            result = response.json()["message"]["content"]
            return result
    except Exception as e:
        print(f"    [WARN] Translation error: {e}")
    return None


async def _generate_edge_tts_fr(text: str, output_path: str) -> bool:
    """Generate French speech using edge-tts with Quebec voice."""
    try:
        import edge_tts
    except ImportError:
        print("  [WARN] edge-tts not installed")
        return False

    voice = "fr-CA-AntoineNeural"
    rate = "+5%"
    pitch = "+0Hz"

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"  [WARN] French edge-tts error: {e}")
        return False


async def _generate_edge_tts(text: str, output_path: str) -> bool:
    """Generate speech using edge-tts (Microsoft Azure neural voices)."""
    try:
        import edge_tts
    except ImportError:
        print("  [WARN] edge-tts not installed")
        return False

    voice = "en-GB-RyanNeural"
    rate = "+10%"
    pitch = "+0Hz"

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"  [WARN] edge-tts error: {e}")
        return False
