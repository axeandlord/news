"""BRIEF webhook server - triggers pipeline runs from the website.

Run with: venv/bin/uvicorn src.webhook:app --host 127.0.0.1 --port 8090
"""

import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure src package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.database import init_database, record_click, record_feedback, mark_segments_heard

PROJECT_ROOT = Path(__file__).parent.parent
WEBHOOK_TOKEN = os.environ.get("BRIEF_WEBHOOK_TOKEN", "")
RATE_LIMIT_SECONDS = 300  # 5 minutes between runs

STEP_LABELS = {
    1: "Fetching RSS feeds",
    2: "Curating articles",
    3: "Researching stories",
    4: "Generating audio",
    5: "Generating deep dives",
    6: "Generating HTML",
    7: "Archiving brief",
}
TOTAL_STEPS = 7

app = FastAPI(title="BRIEF Webhook", docs_url=None, redoc_url=None)
init_database()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://news.bezman.ca", "https://axeandlord.github.io"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Pipeline state
_state = {
    "running": False,
    "last_run": None,
    "last_duration": None,
    "last_error": None,
    "last_trigger": 0,
    "step": None,
    "progress": 0,
}

# Regex to match [N/7] step markers from main.py
_step_re = re.compile(r"\[(\d)/7\]")


def _verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/status")
async def status():
    return {
        "running": _state["running"],
        "last_run": _state["last_run"],
        "last_duration": _state["last_duration"],
        "last_error": _state["last_error"],
        "step": _state["step"],
        "progress": _state["progress"],
    }


@app.post("/trigger")
async def trigger(request: Request):
    _verify_token(request)

    if _state["running"]:
        raise HTTPException(status_code=429, detail="Pipeline already running")

    now = time.time()
    if now - _state["last_trigger"] < RATE_LIMIT_SECONDS:
        remaining = int(RATE_LIMIT_SECONDS - (now - _state["last_trigger"]))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Try again in {remaining}s",
        )

    _state["last_trigger"] = now
    asyncio.create_task(_run_pipeline())

    return {"status": "started", "message": "Pipeline triggered"}


class FeedbackEvent(BaseModel):
    hash: str
    category: str = ""
    action: str  # "click", "like", "dislike"


@app.post("/feedback")
async def feedback(event: FeedbackEvent):
    """Record user feedback (clicks, likes, dislikes) directly into the DB."""
    if event.action == "click":
        record_click(event.hash, event.category)
    elif event.action in ("like", "dislike"):
        record_feedback(event.hash, event.action, event.category)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    return {"status": "ok"}


class HeardEvent(BaseModel):
    heard_hashes: list[str]


@app.post("/heard")
async def report_heard(event: HeardEvent):
    """Record which briefing segments the user has listened to."""
    if not event.heard_hashes:
        raise HTTPException(status_code=400, detail="No hashes provided")
    mark_segments_heard(event.heard_hashes)
    return {"status": "ok"}


async def _run_pipeline():
    _state["running"] = True
    _state["last_error"] = None
    _state["step"] = "Starting"
    _state["progress"] = 0
    start = time.time()
    output_lines = []

    try:
        proc = await asyncio.create_subprocess_exec(
            str(PROJECT_ROOT / "venv" / "bin" / "python"), "-u",
            "-m", "src.main",
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Read stdout line-by-line for real-time progress
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip()
            output_lines.append(line)

            match = _step_re.search(line)
            if match:
                step_num = int(match.group(1))
                _state["step"] = STEP_LABELS.get(step_num, f"Step {step_num}")
                _state["progress"] = int(step_num / TOTAL_STEPS * 100)

        await proc.wait()

        if proc.returncode != 0:
            _state["last_error"] = "\n".join(output_lines[-10:])
            return

        # Push to GitHub Pages
        _state["step"] = "Pushing to GitHub"
        _state["progress"] = 95

        for cmd in [
            ["git", "add", "-A"],
            ["git", "commit", "-m",
             f"Auto-refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"],
            ["git", "push"],
        ]:
            p = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(PROJECT_ROOT),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()

        _state["progress"] = 100
        _state["step"] = "Done"

    except Exception as e:
        _state["last_error"] = str(e)
    finally:
        _state["running"] = False
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        _state["last_duration"] = round(time.time() - start, 1)
