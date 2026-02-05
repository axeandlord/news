"""BRIEF v2 Feedback API.

Simple Flask API to receive feedback from the web interface
and store it in the learning database.

Run with: python -m src.api
Or deploy as serverless function.
"""

import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

from .database import record_click, record_feedback

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from static site


@app.route('/api/feedback', methods=['POST'])
def receive_feedback():
    """
    Receive feedback events from the web client.

    Expected JSON format:
    {
        "events": [
            {
                "type": "click" | "feedback",
                "hash": "article_hash",
                "category": "tech_ai",
                "action": "like" | "dislike" (for feedback type),
                "timestamp": "ISO timestamp"
            }
        ]
    }
    """
    try:
        data = request.get_json()

        if not data or 'events' not in data:
            return jsonify({'error': 'Missing events'}), 400

        events = data['events']
        processed = 0

        for event in events:
            event_type = event.get('type')
            article_hash = event.get('hash')
            category = event.get('category', '')

            if not article_hash:
                continue

            if event_type == 'click':
                record_click(
                    article_hash=article_hash,
                    category=category,
                )
                processed += 1

            elif event_type == 'feedback':
                action = event.get('action')
                if action in ('like', 'dislike'):
                    # Map to feedback types
                    feedback_type = 'like' if action == 'like' else 'dislike'
                    record_feedback(
                        article_hash=article_hash,
                        feedback_type=feedback_type,
                        category=category,
                    )
                    processed += 1

        return jsonify({
            'status': 'ok',
            'processed': processed
        })

    except Exception as e:
        print(f"Feedback API error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'service': 'BRIEF v2 Feedback API',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get engagement statistics."""
    from .database import get_engagement_stats, get_learned_weights

    try:
        stats = get_engagement_stats()
        weights = get_learned_weights()

        return jsonify({
            'engagement': stats,
            'learned_weights': weights
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting BRIEF v2 Feedback API...")
    print("Endpoints:")
    print("  POST /api/feedback - Receive feedback events")
    print("  GET  /api/health   - Health check")
    print("  GET  /api/stats    - Engagement statistics")
    print("")
    app.run(host='0.0.0.0', port=5001, debug=True)
