"""Integration tests: API endpoints and the eval runner end-to-end."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_triage.api.app import app
from agent_triage.engine.classifier import TriageClassifier
from agent_triage.eval.gold import GoldLabel, GoldSet
from agent_triage.eval.runner import run_eval, taxonomy_calibration
from agent_triage.llm.provider import MockProvider
from agent_triage.schema.trace import (
    ActionType,
    AgentRun,
    Observation,
    Step,
    TaskSpec,
    TestResult,
)

client = TestClient(app)


def _env_run(run_id: str) -> AgentRun:
    return AgentRun(
        run_id=run_id, agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id=run_id, problem_statement="p"),
        steps=[
            Step(index=0, action_type=ActionType.COMMAND, content="pytest",
                 observation=Observation(content="ModuleNotFoundError: No module named x",
                                         exit_code=1)),
        ],
        test_result=TestResult(passed=False), resolved=False,
    )


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_taxonomy_endpoint():
    r = client.get("/taxonomy")
    assert r.status_code == 200
    codes = [c["code"] for c in r.json()["categories"]]
    assert "ENVIRONMENT" in codes and "REASONING" in codes


def test_triage_endpoint():
    r = client.post("/triage", json=_env_run("e1").model_dump(mode="json"))
    assert r.status_code == 200
    body = r.json()
    assert body["card"]["primary_category"] == "ENVIRONMENT"
    assert "Root cause" in body["markdown"]


def test_batch_endpoint():
    runs = [_env_run(f"e{i}").model_dump(mode="json") for i in range(3)]
    r = client.post("/triage/batch", json={"runs": runs})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["distribution"].get("ENVIRONMENT") == 3


def test_stats_endpoint():
    runs = [_env_run(f"s{i}").model_dump(mode="json") for i in range(2)]
    r = client.post("/stats", json={"runs": runs})
    assert r.status_code == 200
    assert r.json()["n"] == 2


def test_eval_runner_end_to_end():
    runs = [_env_run("g1"), _env_run("g2")]
    gold = GoldSet(labels=[
        GoldLabel(run_id="g1", task_id="g1", true_category="ENVIRONMENT"),
        GoldLabel(run_id="g2", task_id="g2", true_category="ENVIRONMENT"),
    ])
    report, details = run_eval(runs, gold, TriageClassifier(provider=MockProvider()),
                              bootstrap=False)
    assert report.n == 2
    assert report.accuracy == 1.0
    assert len(details) == 2


def test_calibration_view():
    runs = [_env_run(f"c{i}") for i in range(4)]
    cal = taxonomy_calibration(runs, TriageClassifier(provider=MockProvider()))
    assert cal["n"] == 4
    assert "ENVIRONMENT" in cal["distribution"]
    assert 0.0 <= cal["other_rate"] <= 1.0
