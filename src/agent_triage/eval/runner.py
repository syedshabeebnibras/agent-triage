"""Evaluation runner.

Ties the pieces together: load runs + gold labels, classify each run, pair
predictions with ground truth, and produce an EvalReport. Also computes the
taxonomy-calibration view (per-category frequency and the OTHER rate) so you can
honestly report how the taxonomy held up against real data.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agent_triage.engine.classifier import TriageClassifier
from agent_triage.eval.gold import GoldSet
from agent_triage.eval.metrics import EvalReport, evaluate
from agent_triage.schema.trace import AgentRun


def load_runs(path: str | Path) -> list[AgentRun]:
    """Load runs from a JSONL file (one normalized AgentRun per line)."""
    runs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            runs.append(AgentRun(**json.loads(line)))
    return runs


def run_eval(
    runs: list[AgentRun],
    gold: GoldSet,
    classifier: TriageClassifier,
    *,
    bootstrap: bool = True,
) -> tuple[EvalReport, list[dict]]:
    """Classify each run, pair with gold, evaluate. Returns (report, details)."""
    gold_by_id = gold.by_run_id()
    pairs: list[tuple[str, str]] = []
    details: list[dict] = []

    for run in runs:
        label = gold_by_id.get(run.run_id)
        if label is None:
            continue  # only evaluate runs we have ground truth for
        card = classifier.classify(run)
        pairs.append((label.true_category, card.primary_category))
        details.append(
            {
                "run_id": run.run_id,
                "task_id": run.task.task_id,
                "true": label.true_category,
                "predicted": card.primary_category,
                "correct": label.true_category == card.primary_category,
                "confidence": card.confidence,
                "classifier": card.classifier,
            }
        )

    report = evaluate(pairs, bootstrap=bootstrap)
    return report, details


def taxonomy_calibration(runs: list[AgentRun], classifier: TriageClassifier) -> dict:
    """Distribution of predicted categories across a (possibly unlabeled) set.

    Used to validate the taxonomy against real data: a healthy taxonomy has a low
    OTHER rate and no single category swallowing everything. Recurring patterns in
    OTHER are candidates for new categories.
    """
    counts: Counter[str] = Counter()
    rule_vs_llm: Counter[str] = Counter()
    for run in runs:
        card = classifier.classify(run)
        counts[card.primary_category] += 1
        rule_vs_llm[card.classifier] += 1
    total = sum(counts.values()) or 1
    return {
        "n": total,
        "distribution": dict(counts),
        "other_rate": round(counts.get("OTHER", 0) / total, 4),
        "classifier_split": dict(rule_vs_llm),
    }
