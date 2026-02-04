"""Utility modules for news aggregator."""

from .language import detect_language, is_french, is_english
from .reliability import (
    SourceInfo,
    get_reliability_score,
    calculate_cross_reference_bonus,
    flag_low_reliability,
)

__all__ = [
    "detect_language",
    "is_french",
    "is_english",
    "SourceInfo",
    "get_reliability_score",
    "calculate_cross_reference_bonus",
    "flag_low_reliability",
]
