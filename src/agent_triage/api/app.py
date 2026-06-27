"""FastAPI service for Agent Triage.

Endpoints:
  GET  /health                 -> liveness + provider info
  GET  /taxonomy               -> the failure taxonomy (for the dashboard)
  POST /triage                 -> classify a single AgentRun, return a TriageCard
  POST /triage/batch           -> classify many runs, return cards + distribution
  POST /stats                  -> distribution/calibration over a set of runs

The service is provider-agnostic: it uses the ANTHROPIC_API_KEY if present, else
the offline MockProvider (so the deployed demo runs even without a key, clearly
labeled as mock).
"""

from __future__ import annotations

from collections import Counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo; tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

_provider = default_provider()
_classifier = TriageClassifier(provider=_provider)


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


@app.post("/triage")
def triage(run: AgentRun) -> dict:
    card = _classifier.classify(run)
    return {"card": card.model_dump(mode="json"), "markdown": card.to_markdown()}


@app.post("/triage/batch")
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


@app.post("/stats")
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
