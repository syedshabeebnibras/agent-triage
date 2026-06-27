"""Evaluation metrics for the triage classifier.

Implements the metrics that make a classification claim credible:
  - overall accuracy
  - per-class precision / recall / F1
  - confusion matrix
  - Cohen's kappa (agreement corrected for chance — the honest headline number)
  - bootstrap confidence intervals on accuracy and kappa

No sklearn dependency: these are implemented directly so the package stays light
and the math is auditable. (This mirrors the calibration approach used in
OtelMind: report kappa and CIs, not just raw accuracy.)
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class EvalReport:
    accuracy: float
    kappa: float
    n: int
    per_class: dict[str, ClassMetrics] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    accuracy_ci: tuple[float, float] | None = None
    kappa_ci: tuple[float, float] | None = None

    def to_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 4),
            "kappa": round(self.kappa, 4),
            "n": self.n,
            "accuracy_ci": [round(x, 4) for x in self.accuracy_ci] if self.accuracy_ci else None,
            "kappa_ci": [round(x, 4) for x in self.kappa_ci] if self.kappa_ci else None,
            "per_class": {
                k: {
                    "precision": round(v.precision, 4),
                    "recall": round(v.recall, 4),
                    "f1": round(v.f1, 4),
                    "support": v.support,
                }
                for k, v in self.per_class.items()
            },
            "confusion": self.confusion,
        }


def _accuracy(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    correct = sum(1 for t, p in pairs if t == p)
    return correct / len(pairs)


def _cohens_kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa between true labels and predictions."""
    if not pairs:
        return 0.0
    n = len(pairs)
    labels = sorted({x for pair in pairs for x in pair})
    observed = _accuracy(pairs)

    true_counts: dict[str, int] = defaultdict(int)
    pred_counts: dict[str, int] = defaultdict(int)
    for t, p in pairs:
        true_counts[t] += 1
        pred_counts[p] += 1
    expected = sum((true_counts[lbl] / n) * (pred_counts[lbl] / n) for lbl in labels)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def _per_class(pairs: list[tuple[str, str]]) -> dict[str, ClassMetrics]:
    labels = sorted({x for pair in pairs for x in pair})
    out: dict[str, ClassMetrics] = {}
    for lbl in labels:
        tp = sum(1 for t, p in pairs if t == lbl and p == lbl)
        fp = sum(1 for t, p in pairs if t != lbl and p == lbl)
        fn = sum(1 for t, p in pairs if t == lbl and p != lbl)
        support = sum(1 for t, _ in pairs if t == lbl)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[lbl] = ClassMetrics(precision, recall, f1, support)
    return out


def _confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    labels = sorted({x for pair in pairs for x in pair})
    matrix = {t: {p: 0 for p in labels} for t in labels}
    for t, p in pairs:
        matrix[t][p] += 1
    return matrix


def _bootstrap_ci(
    pairs: list[tuple[str, str]],
    stat_fn,
    *,
    iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Percentile bootstrap CI for a statistic over (true, pred) pairs."""
    if not pairs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(pairs)
    stats = []
    for _ in range(iterations):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        stats.append(stat_fn(sample))
    stats.sort()
    lo = stats[int((alpha / 2) * iterations)]
    hi = stats[int((1 - alpha / 2) * iterations) - 1]
    return (lo, hi)


def evaluate(
    pairs: list[tuple[str, str]], *, bootstrap: bool = True, iterations: int = 1000
) -> EvalReport:
    """Compute the full evaluation report from (true, predicted) label pairs."""
    report = EvalReport(
        accuracy=_accuracy(pairs),
        kappa=_cohens_kappa(pairs),
        n=len(pairs),
        per_class=_per_class(pairs),
        confusion=_confusion(pairs),
    )
    if bootstrap and pairs:
        report.accuracy_ci = _bootstrap_ci(pairs, _accuracy, iterations=iterations)
        report.kappa_ci = _bootstrap_ci(pairs, _cohens_kappa, iterations=iterations)
    return report
