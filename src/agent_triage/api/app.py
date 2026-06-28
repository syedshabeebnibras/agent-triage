"""FastAPI service for Agent Triage.

Endpoints:
  GET  /health                      -> liveness + provider info
  GET  /taxonomy                    -> the failure taxonomy (for the dashboard)
  GET  /triage/demo                 -> pre-classified demo batch (public, cached)
  POST /triage                      -> classify a single AgentRun, return a TriageCard
  POST /triage/batch                -> classify many runs, return cards + distribution
  POST /stats                       -> distribution/calibration over a set of runs
  GET  /stats/trend                 -> batch trend history (SQLite-backed)
  POST /cards/{run_id}/correct      -> record a human correction for a triage result
  GET  /corrections                 -> list all human corrections

Authentication
--------------
When TRIAGE_API_KEY is set in the environment AND the server is running with a
real LLM provider (not mock mode), the triage endpoints require:

    Authorization: Bearer <TRIAGE_API_KEY>

/health, /taxonomy, /triage/demo, /stats/trend, and /corrections are public.
In mock mode the auth gate is skipped — safe because no API credits are spent.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_provider = default_provider()
_classifier = TriageClassifier(provider=_provider)
_TRIAGE_API_KEY = os.getenv("TRIAGE_API_KEY")

# SQLite path: use /data/triage.db if the directory exists (Render disk mount),
# otherwise fall back to a local file. This survives container restarts when
# a persistent disk is attached in Render settings (Settings → Disks → /data).
_DB_PATH = Path(os.getenv("TRIAGE_DB_PATH", "/data/triage.db" if Path("/data").exists() else "triage.db"))


def _init_db() -> None:
    """Create tables if they don't exist yet."""
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trend_log (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       REAL    NOT NULL,
                count    INTEGER NOT NULL,
                distribution TEXT NOT NULL,
                owner_distribution TEXT NOT NULL,
                rule_rate REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS corrections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id     TEXT    NOT NULL,
                auto_label TEXT    NOT NULL,
                true_label TEXT    NOT NULL,
                note       TEXT,
                created_at REAL    NOT NULL
            );
        """)


@contextmanager
def _db():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_init_db()


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


@app.get("/triage/cards")
def triage_cards() -> dict:
    """Serve pre-classified TriageCards from a JSONL file without re-classifying.

    The /triage/demo endpoint re-runs classification on raw AgentRun objects.
    This endpoint serves already-classified cards directly — useful for large
    batches that were pre-classified offline.
    """
    cards_path = Path("data/traces/new_cards.jsonl")
    if not cards_path.exists():
        return {
            "count": 0,
            "cards": [],
            "distribution": {},
            "owner_distribution": {},
            "mock_mode": False,
        }
    cards_raw = []
    with open(cards_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cards_raw.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    dist: Counter[str] = Counter(c.get("primary_category", "UNKNOWN") for c in cards_raw)
    owners: Counter[str] = Counter(c.get("owner", "unknown") for c in cards_raw)
    return {
        "count": len(cards_raw),
        "cards": cards_raw,
        "distribution": dict(dist),
        "owner_distribution": dict(owners),
        "mock_mode": False,
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
    rule_rate = round(sum(1 for c in cards if c.classifier == "rule") / max(len(cards), 1), 4)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO trend_log (ts, count, distribution, owner_distribution, rule_rate) VALUES (?,?,?,?,?)",
                (time.time(), len(cards), json.dumps(dict(dist)), json.dumps(dict(owners)), rule_rate),
            )
    except Exception as exc:
        _log.warning("trend_log write failed: %s", exc)
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
def stats_trend(limit: int = 50) -> dict:
    """Return the history of /triage/batch calls, newest first (SQLite-backed).

    Survives container restarts when a persistent disk is mounted at /data.
    Falls back to the local triage.db file when /data is unavailable.
    """
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT ts, count, distribution, owner_distribution, rule_rate "
                "FROM trend_log ORDER BY ts DESC LIMIT ?",
                (min(limit, 500),),
            ).fetchall()
        batches = [
            {
                "ts": r["ts"],
                "count": r["count"],
                "distribution": json.loads(r["distribution"]),
                "owner_distribution": json.loads(r["owner_distribution"]),
                "rule_rate": r["rule_rate"],
            }
            for r in rows
        ]
    except Exception as exc:
        _log.warning("trend_log read failed: %s", exc)
        batches = []
    return {
        "batches": batches,
        "total_batches_recorded": len(batches),
        "db_path": str(_DB_PATH),
    }


class CorrectionRequest(BaseModel):
    true_label: str
    note: str | None = None


@app.post("/cards/{run_id}/correct")
def correct_card(run_id: str, req: CorrectionRequest) -> dict:
    """Record a human correction for an auto-classified triage card.

    This is the feedback loop: when a support engineer disagrees with the
    classifier verdict, they POST the correct label here. Corrections are
    stored in SQLite and surfaced via GET /corrections for periodic review
    to improve rule thresholds and the gold set.
    """
    from agent_triage.taxonomy.categories import is_valid

    if not is_valid(req.true_label.upper()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown taxonomy code '{req.true_label}'. Must be one of: {', '.join(TAXONOMY.keys())}",
        )
    try:
        with _db() as conn:
            # fetch the most recent auto classification for this run_id from cards table
            # (we don't store individual cards in DB yet — record auto_label as unknown
            # if not tracked; a future migration can backfill from card JSONL exports)
            conn.execute(
                "INSERT INTO corrections (run_id, auto_label, true_label, note, created_at) VALUES (?,?,?,?,?)",
                (run_id, "unknown", req.true_label.upper(), req.note, time.time()),
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB write failed: {exc}") from exc
    return {"run_id": run_id, "true_label": req.true_label.upper(), "recorded": True}


@app.get("/corrections")
def list_corrections(limit: int = 100) -> dict:
    """Return all recorded human corrections, newest first."""
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT run_id, auto_label, true_label, note, created_at "
                "FROM corrections ORDER BY created_at DESC LIMIT ?",
                (min(limit, 1000),),
            ).fetchall()
        corrections = [dict(r) for r in rows]
    except Exception as exc:
        _log.warning("corrections read failed: %s", exc)
        corrections = []
    return {"corrections": corrections, "count": len(corrections)}
