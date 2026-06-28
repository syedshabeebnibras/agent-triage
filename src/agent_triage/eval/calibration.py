"""Confidence calibration for the triage classifier.

A well-calibrated classifier means: when it says "confidence 0.80", it is
actually correct ~80% of the time. Without calibration, raw model confidence
scores are often overconfident (scores cluster near 1.0) or systematically
biased.

We use Platt scaling — a logistic regression fit on top of the raw confidence
scores using gold-labeled examples. This is simple, interpretable, and works
well with small calibration sets (30–100 examples).

Usage
-----
    from agent_triage.eval.calibration import CalibrationFitter, plot_reliability

    # fit on gold set
    fitter = CalibrationFitter()
    fitter.fit(raw_confidences, correctness_flags)

    # apply to new scores
    calibrated = [fitter.transform(c) for c in raw_scores]

    # reliability diagram (text-only, no matplotlib required)
    print(plot_reliability(raw_confidences, correctness_flags))
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class CalibrationFitter:
    """Platt scaling: fit a logistic function to map raw confidence → calibrated probability.

    Parameters (learned from fit()):
        a, b  — logistic coefficients such that P(correct) = sigmoid(a * raw + b)
    """

    a: float = 1.0
    b: float = 0.0
    _fitted: bool = field(default=False, repr=False)

    def fit(self, confidences: list[float], correct: list[bool], *, lr: float = 0.1, steps: int = 200) -> None:
        """Fit Platt scaling via gradient descent on binary cross-entropy.

        Parameters
        ----------
        confidences : list[float]
            Raw confidence scores in [0, 1] from the classifier.
        correct : list[bool]
            Whether the classifier was correct for each prediction.
        lr : float
            Learning rate.
        steps : int
            Gradient descent iterations.
        """
        if len(confidences) != len(correct):
            raise ValueError("confidences and correct must have the same length")
        if len(confidences) < 2:
            raise ValueError("Need at least 2 examples to fit calibration")

        a, b = self.a, self.b
        n = len(confidences)

        for _ in range(steps):
            da, db = 0.0, 0.0
            for x, y in zip(confidences, correct, strict=True):
                p = _sigmoid(a * x + b)
                err = p - (1.0 if y else 0.0)
                da += err * x
                db += err
            a -= lr * da / n
            b -= lr * db / n

        self.a = a
        self.b = b
        self._fitted = True

    def transform(self, raw_confidence: float) -> float:
        """Map a raw confidence score to a calibrated probability."""
        return _sigmoid(self.a * raw_confidence + self.b)

    def to_dict(self) -> dict[str, float]:
        return {"a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> CalibrationFitter:
        obj = cls()
        obj.a = d["a"]
        obj.b = d["b"]
        obj._fitted = True
        return obj


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass
class CalibrationReport:
    """Reliability diagram data: expected confidence vs observed accuracy per bin."""

    bins: list[dict]  # [{bin_mid, mean_confidence, accuracy, count}]
    expected_calibration_error: float  # ECE — weighted mean absolute gap
    max_calibration_error: float  # MCE — worst-bin gap


def reliability_report(
    confidences: list[float],
    correct: list[bool],
    *,
    n_bins: int = 5,
) -> CalibrationReport:
    """Compute reliability diagram data and calibration error metrics.

    Parameters
    ----------
    confidences : list[float]
        Predicted confidence scores.
    correct : list[bool]
        Ground-truth correctness flags.
    n_bins : int
        Number of equal-width bins in [0, 1].

    Returns
    -------
    CalibrationReport with per-bin stats, ECE, and MCE.
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must have the same length")

    bins: list[dict] = []
    bin_width = 1.0 / n_bins
    n = len(confidences)

    for i in range(n_bins):
        lo, hi = i * bin_width, (i + 1) * bin_width
        in_bin = [(c, y) for c, y in zip(confidences, correct, strict=True) if lo <= c < hi]
        if not in_bin:
            continue
        mean_conf = sum(c for c, _ in in_bin) / len(in_bin)
        accuracy = sum(1 for _, y in in_bin if y) / len(in_bin)
        bins.append({
            "bin_mid": (lo + hi) / 2,
            "mean_confidence": round(mean_conf, 4),
            "accuracy": round(accuracy, 4),
            "count": len(in_bin),
        })

    ece = sum(abs(b["mean_confidence"] - b["accuracy"]) * b["count"] / n for b in bins)
    mce = max((abs(b["mean_confidence"] - b["accuracy"]) for b in bins), default=0.0)

    return CalibrationReport(
        bins=bins,
        expected_calibration_error=round(ece, 4),
        max_calibration_error=round(mce, 4),
    )


def format_reliability_diagram(report: CalibrationReport) -> str:
    """Render a text reliability diagram for terminal / log output."""
    lines = ["Reliability diagram (confidence → accuracy per bin)"]
    lines.append(f"{'Bin':>10}  {'Mean conf':>10}  {'Accuracy':>10}  {'Count':>6}  Gap")
    lines.append("-" * 56)
    for b in report.bins:
        gap = b["mean_confidence"] - b["accuracy"]
        marker = "▲" if gap > 0.05 else ("▼" if gap < -0.05 else "≈")
        lines.append(
            f"{b['bin_mid']:>10.2f}  {b['mean_confidence']:>10.3f}  "
            f"{b['accuracy']:>10.3f}  {b['count']:>6}  {marker}{abs(gap):.3f}"
        )
    lines.append("-" * 56)
    lines.append(f"ECE={report.expected_calibration_error:.4f}  MCE={report.max_calibration_error:.4f}")
    lines.append("(ECE < 0.05 is well-calibrated; > 0.10 needs calibration.)")
    return "\n".join(lines)
