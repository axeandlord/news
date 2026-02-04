"""Language detection utilities."""

from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# Make detection deterministic
DetectorFactory.seed = 0


def detect_language(text: str) -> str:
    """
    Detect the language of text.

    Returns 'en' or 'fr' (defaults to 'en' if uncertain).
    """
    if not text or len(text.strip()) < 20:
        return "en"

    try:
        lang = detect(text)
        # Map to our supported languages
        if lang == "fr":
            return "fr"
        return "en"
    except LangDetectException:
        return "en"


def is_french(text: str) -> bool:
    """Check if text is French."""
    return detect_language(text) == "fr"


def is_english(text: str) -> bool:
    """Check if text is English."""
    return detect_language(text) == "en"
