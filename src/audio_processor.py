"""Audio post-processing pipeline.

Enhances TTS output with normalization, compression, EQ, and format conversion.
Uses FFmpeg for all processing.
"""

import subprocess
from pathlib import Path


def process_audio(
    input_path: str,
    output_path: str,
    target_loudness: float = -18,  # LUFS - softer, less fatiguing
    bitrate: str = "192k",
) -> bool:
    """
    Process audio with professional-quality enhancements.

    Pipeline:
    1. High-pass filter (80Hz) - removes rumble
    2. Compressor (gentle) - evens out dynamics
    3. Loudness normalization (EBU R128)
    4. Slight warmth EQ
    5. Convert to MP3

    Args:
        input_path: Path to input WAV file
        output_path: Path for output MP3
        target_loudness: Target loudness in LUFS (default -16)
        bitrate: MP3 bitrate (default 192k)

    Returns:
        True if successful
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        print(f"  [WARN] Input file not found: {input_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build FFmpeg filter chain - LIGHT processing for natural sound
    # Keep it simple - just normalize and gentle highpass
    filters = [
        "highpass=f=60",  # Very gentle, just remove rumble
        f"loudnorm=I={target_loudness}:TP=-2:LRA=14",  # More dynamic range (LRA=14)
    ]
    # NO compression, NO EQ boost - keep the natural voice

    filter_chain = ",".join(filters)

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", str(input_path),
        "-af", filter_chain,
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            size = output_path.stat().st_size
            print(f"  Processed audio: {output_path} ({size / 1024:.1f} KB)")
            return True
        else:
            print(f"  [WARN] FFmpeg error: {result.stderr[-500:]}")
            return False

    except subprocess.TimeoutExpired:
        print("  [WARN] Audio processing timed out")
        return False
    except Exception as e:
        print(f"  [WARN] Audio processing error: {e}")
        return False


def concatenate_segments(paths: list[str], output: str) -> bool:
    """Concatenate multiple MP3 files into one using ffmpeg concat demuxer.

    Args:
        paths: List of MP3 file paths in order
        output: Output file path

    Returns:
        True if successful
    """
    if not paths:
        return False

    if len(paths) == 1:
        import shutil
        shutil.copy(paths[0], output)
        return True

    # Write concat list file
    list_path = Path(output).parent / "concat_list.txt"
    try:
        with open(list_path, "w") as f:
            for p in paths:
                # ffmpeg concat requires absolute paths with escaped quotes
                f.write(f"file '{Path(p).absolute()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            print(f"  Concatenated {len(paths)} segments into {output}")
            return True
        else:
            print(f"  [WARN] Concat error: {result.stderr[-300:]}")
            return False

    except Exception as e:
        print(f"  [WARN] Concat error: {e}")
        return False
    finally:
        if list_path.exists():
            list_path.unlink()


def get_audio_duration(path: str) -> float:
    """Get audio duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass

    return 0.0


def get_audio_info(path: str) -> dict:
    """Get audio file information."""
    path = Path(path)
    if not path.exists():
        return {}

    duration = get_audio_duration(str(path))
    size = path.stat().st_size

    return {
        "path": str(path),
        "duration": duration,
        "duration_str": f"{int(duration // 60)}:{int(duration % 60):02d}",
        "size_kb": size / 1024,
        "bitrate_kbps": (size * 8 / duration / 1000) if duration > 0 else 0,
    }


if __name__ == "__main__":
    # Test
    import sys

    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace(".wav", "_processed.mp3")
        success = process_audio(input_file, output_file)
        if success:
            info = get_audio_info(output_file)
            print(f"Duration: {info['duration_str']}")
            print(f"Size: {info['size_kb']:.1f} KB")
    else:
        print("Usage: python audio_processor.py input.wav [output.mp3]")
