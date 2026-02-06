"""Import feedback from browser-exported JSON into the learning database.

Usage: python -m src.import_feedback feedback.json
"""

import json
import sys

from .database import record_click, record_feedback


def import_feedback(path: str):
    """Import feedback JSON exported from the BRIEF web interface."""
    with open(path) as f:
        data = json.load(f)

    click_count = 0
    feedback_count = 0

    for article_hash, click_data in data.get("clicks", {}).items():
        category = click_data.get("category", "")
        record_click(article_hash, category)
        click_count += 1

    for article_hash, fb_data in data.get("feedback", {}).items():
        action = fb_data.get("action", "")
        category = fb_data.get("category", "")
        if action in ("like", "dislike"):
            record_feedback(article_hash, action, category)
            feedback_count += 1

    print(f"Imported {click_count} clicks, {feedback_count} feedback entries")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.import_feedback <feedback.json>")
        sys.exit(1)
    import_feedback(sys.argv[1])
