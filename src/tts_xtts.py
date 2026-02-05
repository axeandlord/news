"""XTTS v2 Text-to-Speech integration.

Uses Coqui TTS with XTTS v2 model running on local GPU.
Requires the 'xtts' micromamba environment with Python 3.11.
"""

import subprocess
import tempfile
from pathlib import Path

# Path to micromamba and the xtts environment
MICROMAMBA = "/home/axe/.local/bin/micromamba"
XTTS_ENV = "xtts"

# JARVIS voice reference - Paul Bettany style British butler
# Primary: Real JARVIS sample, Fallback: VCTK VITS p243 speaker
VOICE_REFERENCE_JARVIS = Path(__file__).parent.parent / "audio" / "voice_reference_jarvis.wav"
VOICE_REFERENCE_FALLBACK = Path(__file__).parent.parent / "audio" / "voice_reference.wav"

def get_voice_reference() -> Path:
    """Get the best available voice reference."""
    if VOICE_REFERENCE_JARVIS.exists():
        return VOICE_REFERENCE_JARVIS
    return VOICE_REFERENCE_FALLBACK


def ensure_voice_reference() -> Path:
    """Ensure we have a voice reference file for XTTS."""
    voice_ref = get_voice_reference()
    if voice_ref.exists():
        return voice_ref

    print("  Generating voice reference...")
    # Generate a British voice sample using VCTK VITS
    script = '''
import warnings
warnings.filterwarnings('ignore')
from TTS.api import TTS
tts = TTS('tts_models/en/vctk/vits').to('cuda')
sample_text = "Good morning sir. I have compiled your daily briefing with today's most relevant news. Shall we begin with the top stories?"
tts.tts_to_file(text=sample_text, file_path="{output}", speaker='p243')
print("Generated voice reference")
'''.format(output=str(VOICE_REFERENCE_FALLBACK))

    result = subprocess.run(
        [MICROMAMBA, "run", "-n", XTTS_ENV, "python", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"  [WARN] Voice reference generation failed: {result.stderr}")
        return None

    return VOICE_REFERENCE


def generate_xtts(
    text: str,
    output_path: str,
    voice_reference: str = None,
    language: str = "en",
) -> bool:
    """
    Generate speech using XTTS v2.

    Args:
        text: Text to convert to speech
        output_path: Path to save the WAV output
        voice_reference: Path to voice reference WAV (uses default British if None)
        language: Language code (default: en)

    Returns:
        True if successful, False otherwise
    """
    if not text.strip():
        return False

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Get voice reference
    if voice_reference is None:
        voice_reference = ensure_voice_reference()
        if voice_reference is None:
            print("  [WARN] No voice reference available")
            return False

    # Build the generation script
    # We use subprocess because XTTS requires Python 3.11 environment
    script = f'''
import warnings
warnings.filterwarnings('ignore')
from TTS.api import TTS
import time

# Load XTTS
tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2').to('cuda')

# Text to synthesize
text = """{text.replace('"', '\\"').replace('\n', ' ')}"""

# Generate
start = time.time()
tts.tts_to_file(
    text=text,
    file_path="{output_path}",
    speaker_wav="{voice_reference}",
    language="{language}"
)
elapsed = time.time() - start
print(f"Generated in {{elapsed:.1f}}s")
'''

    try:
        result = subprocess.run(
            [MICROMAMBA, "run", "-n", XTTS_ENV, "python", "-c", script],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes max
        )

        if result.returncode == 0:
            print(f"  XTTS: {result.stdout.strip()}")
            return Path(output_path).exists()
        else:
            print(f"  [WARN] XTTS error: {result.stderr[:500]}")
            return False

    except subprocess.TimeoutExpired:
        print("  [WARN] XTTS generation timed out")
        return False
    except Exception as e:
        print(f"  [WARN] XTTS error: {e}")
        return False


def test_xtts():
    """Test XTTS generation."""
    test_text = """Good evening, sir. I've been keeping an eye on things and have a few items worth your attention.
    Google dropped some rather impressive numbers today. Gemini has apparently hit 750 million monthly users.
    That's significant because it puts them ahead of ChatGPT in raw usage, at least by their count."""

    output = "/tmp/xtts_test.wav"
    success = generate_xtts(test_text, output)

    if success:
        import os
        size = os.path.getsize(output)
        print(f"Test successful: {output} ({size / 1024:.1f} KB)")
    else:
        print("Test failed")

    return success


if __name__ == "__main__":
    test_xtts()
