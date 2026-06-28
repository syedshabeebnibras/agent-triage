"""FastAPI service for Agent Triage.

Endpoints:
  GET  /health                 -> liveness + provider info
  GET  /taxonomy               -> the failure taxonomy (for the dashboard)
  GET  /triage/demo            -> pre-classified demo batch (public, cached)
  POST /triage                 -> classify a single AgentRun, return a TriageCard
  POST /triage/batch           -> classify many runs, return cards + distribution
  POST /stats                  -> distribution/calibration over a set of runs
  GET  /stats/trend            -> session trend of batch results over time

Authentication
--------------
When TRIAGE_API_KEY is set in the environment AND the server is running with a
real LLM provider (not mock mode), the three LLM-calling endpoints require:

    Authorization: Bearer <TRIAGE_API_KEY>

/health, /taxonomy, /triage/demo, and /stats/trend are always unauthenticated.
In mock mode the auth gate is skipped — safe because no API credits are spent.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from agent_triage import __version__
from agent_triage.engine.classifier import TriageClassifier
from agent_triage.llm.provider import default_provider
from agent_triage.schema.trace import AgentRun
from agent_triage.taxonomy.categories import TAXONOMY, TAXONOMY_VERSION

_log = logging.getLogger("agent_triage.api")

app = FastAPI(
    title="Agent Triage API",
    version=__version__,
    description="Failure triage and root-cause analysis for autonomous coding-agent runs.",
)

# CORS: allow all origins for the demo dashboard.
# Tighten allow_origins to your dashboard domain for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_provider = default_provider()
_classifier = TriageClassifier(provider=_provider)
_TRIAGE_API_KEY = os.getenv("TRIAGE_API_KEY")

# In-memory ring buffer for trend tracking (last 50 batch results)
_trend_log: deque[dict[str, Any]] = deque(maxlen=50)


def _build_demo_cache() -> dict | None:
    """Classify the bundled demo runs once at startup and cache the result.

    The /triage/demo endpoint is public (no auth required) — it only ever
    classifies this fixed set of 9 demo runs, so there are no LLM credits
    exposed to arbitrary callers.
    """
    demo_path = Path("data/traces/demo_runs.jsonl")
    if not demo_path.exists():
        return None
    try:
        runs = [
            AgentRun(**json.loads(line))
            for line in demo_path.read_text().splitlines()
            if line.strip()
        ]
        cards = [_classifier.classify(r) for r in runs]
        dist: Counter[str] = Counter(c.primary_category for c in cards)
        owners: Counter[str] = Counter(c.owner.value for c in cards)
        return {
            "count": len(cards),
            "cards": [c.model_dump(mode="json") for c in cards],
            "distribution": dict(dist),
            "owner_distribution": dict(owners),
            "mock_mode": _provider.name == "mock",
        }
    except Exception:
        return None


_demo_cache: dict | None = _build_demo_cache()

_bearer = HTTPBearer(auto_error=False)


@app.middleware("http")
async def _request_logger(request: Request, call_next):
    """Log every request as a structured JSON line for observability."""
    t0 = time.monotonic()
    response = await call_next(request)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    _log.info(
        json.dumps({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": elapsed_ms,
        })
    )
    return response


def _require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> None:
    """Gate for LLM-calling endpoints.

    Skipped when no TRIAGE_API_KEY is configured (local dev / CI) or when
    running in mock mode (no real API credits at stake).
    """
    if _TRIAGE_API_KEY is None or _provider.name == "mock":
        return
    if credentials is None or credentials.credentials != _TRIAGE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Set Authorization: Bearer <TRIAGE_API_KEY>.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class BatchRequest(BaseModel):
    runs: list[AgentRun]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "provider": _provider.name,
        "mock_mode": _provider.name == "mock",
        "taxonomy_version": TAXONOMY_VERSION,
        "auth_required": _TRIAGE_API_KEY is not None and _provider.name != "mock",
    }


@app.get("/taxonomy")
def taxonomy() -> dict:
    return {
        "version": TAXONOMY_VERSION,
        "categories": [
            {
                "code": c.code,
                "name": c.name,
                "definition": c.definition,
                "owner": c.typical_owner.value,
                "signals": c.signals,
                "recommended_action": c.recommended_action,
                "prevention": c.prevention,
            }
            for c in TAXONOMY.values()
        ],
    }


@app.get("/triage/demo")
def triage_demo() -> dict:
    """Public endpoint: pre-classified demo batch, cached at startup.

    Classifies the bundled 9-run demo set exactly once (on container start) and
    serves the cached result. No auth required — the fixed demo set is not a
    credit-draining path.
    """
    if _demo_cache is not None:
        return _demo_cache
    # demo_runs.jsonl not present in this deployment; return empty batch
    return {
        "count": 0,
        "cards": [],
        "distribution": {},
        "owner_distribution": {},
        "mock_mode": _provider.name == "mock",
    }


@app.post("/triage", dependencies=[Depends(_require_auth)])
def triage(run: AgentRun) -> dict:
    card = _classifier.classify(run)
    return {"card": card.model_dump(mode="json"), "markdown": card.to_markdown()}


@app.post("/triage/batch", dependencies=[Depends(_require_auth)])
def triage_batch(req: BatchRequest) -> dict:
    cards = [_classifier.classify(r) for r in req.runs]
    dist: Counter[str] = Counter(c.primary_category for c in cards)
    owners: Counter[str] = Counter(c.owner.value for c in cards)
    result = {
        "count": len(cards),
        "cards": [c.model_dump(mode="json") for c in cards],
        "distribution": dict(dist),
        "owner_distribution": dict(owners),
        "mock_mode": _provider.name == "mock",
    }
    # record in trend log (snapshot without cards to keep memory small)
    _trend_log.append({
        "ts": time.time(),
        "count": result["count"],
        "distribution": result["distribution"],
        "owner_distribution": result["owner_distribution"],
        "rule_rate": round(
            sum(1 for c in cards if c.classifier == "rule") / max(len(cards), 1), 4
        ),
    })
    return result


@app.post("/stats", dependencies=[Depends(_require_auth)])
def stats(req: BatchRequest) -> dict:
    cards = [_classifier.classify(r) for r in req.runs]
    dist: Counter[str] = Counter(c.primary_category for c in cards)
    by_classifier: Counter[str] = Counter(c.classifier for c in cards)
    total = len(cards) or 1
    return {
        "n": len(cards),
        "distribution": dict(dist),
        "other_rate": round(dist.get("OTHER", 0) / total, 4),
        "classifier_split": dict(by_classifier),
    }


@app.get("/stats/trend")
def stats_trend() -> dict:
    """Return the session history of /triage/batch calls (last 50).

    Each entry records when the batch was submitted, the run count, the
    category distribution, and the rule-vs-LLM split. Useful for monitoring
    whether failure-mode rates are shifting across batches over time.

    Note: this is an in-memory ring buffer — it resets on container restart.
    For persistent trend storage, export to a time-series DB.
    """
    return {
        "batches": list(_trend_log),
        "total_batches_recorded": len(_trend_log),
        "note": "In-memory only; resets on container restart.",
    }
