"""BRIEF webhook server - triggers pipeline runs from the website.

Run with: venv/bin/uvicorn src.webhook:app --host 127.0.0.1 --port 8090
"""

import asyncio
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).parent.parent
WEBHOOK_TOKEN = os.environ.get("BRIEF_WEBHOOK_TOKEN", "")
RATE_LIMIT_SECONDS = 600  # 10 minutes between runs

app = FastAPI(title="BRIEF Webhook", docs_url=None, redoc_url=None)

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
}


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


async def _run_pipeline():
    _state["running"] = True
    _state["last_error"] = None
    start = time.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            str(PROJECT_ROOT / "venv" / "bin" / "python"),
            "-m", "src.main",
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            _state["last_error"] = stdout.decode()[-500:] if stdout else "Unknown error"
            return

        # Auto-push to GitHub Pages
        push_proc = await asyncio.create_subprocess_exec(
            "git", "add", "-A",
            cwd=str(PROJECT_ROOT),
        )
        await push_proc.communicate()

        push_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m",
            f"Auto-refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            cwd=str(PROJECT_ROOT),
        )
        await push_proc.communicate()

        push_proc = await asyncio.create_subprocess_exec(
            "git", "push",
            cwd=str(PROJECT_ROOT),
        )
        await push_proc.communicate()

    except Exception as e:
        _state["last_error"] = str(e)
    finally:
        _state["running"] = False
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        _state["last_duration"] = round(time.time() - start, 1)
