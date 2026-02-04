"""Text-to-Speech generation using piper-tts."""

import subprocess
from pathlib import Path

from .curator import CuratedArticle
from .utils.language import detect_language


def generate_tts_script(sections: dict[str, list[CuratedArticle]]) -> tuple[str, str]:
    """
    Generate TTS script from curated articles.

    Returns (english_script, french_script) tuple.
    """
    en_lines = ["Here's your daily news brief."]
    fr_lines = ["Voici votre bulletin d'informations quotidien."]

    for section_name, articles in sections.items():
        if not articles:
            continue

        en_lines.append(f"{section_name}.")
        fr_lines.append(f"{section_name}.")

        for item in articles:
            article = item.article
            title = article.title
            source = article.source

            # Use AI summary if available, else truncated original
            summary = item.ai_summary or article.summary[:150]

            # Detect language and add to appropriate script
            lang = detect_language(f"{title} {summary}")

            line = f"{title}. From {source}. {summary}"

            if lang == "fr":
                fr_lines.append(line)
            else:
                en_lines.append(line)

    en_lines.append("That's all for today's news brief.")
    fr_lines.append("C'est tout pour le bulletin d'aujourd'hui.")

    return "\n".join(en_lines), "\n".join(fr_lines)


def text_to_speech(
    text: str,
    output_path: str,
    voice: str = "en_US-amy-medium",
    rate: int = 160
) -> bool:
    """
    Convert text to speech using piper-tts.

    Returns True if successful.
    """
    if not text.strip():
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Piper expects text on stdin, outputs WAV
        wav_path = output_path.with_suffix(".wav")

        # Run piper
        result = subprocess.run(
            [
                "piper",
                "--model", voice,
                "--output_file", str(wav_path),
                "--length_scale", str(1.0 / (rate / 160)),  # Adjust speaking rate
            ],
            input=text,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )

        if result.returncode != 0:
            print(f"  [WARN] Piper error: {result.stderr}")
            return False

        # Convert WAV to MP3 using ffmpeg
        mp3_result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(wav_path),
                "-codec:a", "libmp3lame",
                "-b:a", "128k",
                str(output_path),
            ],
            capture_output=True,
            timeout=120,
        )

        # Clean up WAV
        wav_path.unlink(missing_ok=True)

        if mp3_result.returncode != 0:
            print(f"  [WARN] FFmpeg error")
            return False

        print(f"  Generated {output_path}")
        return True

    except FileNotFoundError:
        print("  [WARN] piper or ffmpeg not found, skipping TTS")
        return False
    except subprocess.TimeoutExpired:
        print("  [WARN] TTS timeout")
        return False
    except Exception as e:
        print(f"  [WARN] TTS error: {e}")
        return False


def generate_audio_brief(
    sections: dict[str, list[CuratedArticle]],
    output_dir: str = "audio",
    en_voice: str = "en_US-amy-medium",
    fr_voice: str = "fr_FR-siwis-medium"
) -> str | None:
    """
    Generate audio briefing from curated articles.

    Returns path to combined audio file, or None if failed.
    """
    en_script, fr_script = generate_tts_script(sections)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("Generating TTS audio...")

    # Generate English audio (primary)
    en_path = output_path / "brief-en.mp3"
    en_success = text_to_speech(en_script, str(en_path), voice=en_voice)

    # Generate French audio if there's French content
    if len(fr_script.split("\n")) > 3:  # More than just intro/outro
        fr_path = output_path / "brief-fr.mp3"
        text_to_speech(fr_script, str(fr_path), voice=fr_voice)

    if en_success:
        return "audio/brief-en.mp3"

    return None


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
        ai_summary="OpenAI unveiled a new AI model today.",
    )

    sections = {"Top Stories": [test_curated]}
    generate_audio_brief(sections)
