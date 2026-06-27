"""FastAPI service for Agent Triage.

Endpoints:
  GET  /health                 -> liveness + provider info
  GET  /taxonomy               -> the failure taxonomy (for the dashboard)
  POST /triage                 -> classify a single AgentRun, return a TriageCard
  POST /triage/batch           -> classify many runs, return cards + distribution
  POST /stats                  -> distribution/calibration over a set of runs

Authentication
--------------
When TRIAGE_API_KEY is set in the environment AND the server is running with a
real LLM provider (not mock mode), the three LLM-calling endpoints require:

    Authorization: Bearer <TRIAGE_API_KEY>

/health and /taxonomy are always unauthenticated (no credits at risk).
In mock mode the auth gate is skipped — safe because no API credits are spent.
"""

from __future__ import annotations

import os
from collections import Counter

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from agent_triage import __version__
from agent_triage.engine.classifier import TriageClassifier
from agent_triage.llm.provider import default_provider
from agent_triage.schema.trace import AgentRun
from agent_triage.taxonomy.categories import TAXONOMY, TAXONOMY_VERSION

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

_bearer = HTTPBearer(auto_error=False)


def _require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
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


@app.post("/triage", dependencies=[Depends(_require_auth)])
def triage(run: AgentRun) -> dict:
    card = _classifier.classify(run)
    return {"card": card.model_dump(mode="json"), "markdown": card.to_markdown()}


@app.post("/triage/batch", dependencies=[Depends(_require_auth)])
def triage_batch(req: BatchRequest) -> dict:
    cards = [_classifier.classify(r) for r in req.runs]
    dist: Counter[str] = Counter(c.primary_category for c in cards)
    owners: Counter[str] = Counter(c.owner.value for c in cards)
    return {
        "count": len(cards),
        "cards": [c.model_dump(mode="json") for c in cards],
        "distribution": dict(dist),
        "owner_distribution": dict(owners),
        "mock_mode": _provider.name == "mock",
    }


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
