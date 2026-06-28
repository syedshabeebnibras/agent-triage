"""Inter-annotator agreement (IAA) report for the triage gold set.

Computes Cohen's kappa between two labelers on their shared overlap runs.
This is the measurement missing from the current single-labeler gold set —
κ=1.000 with one annotator means self-consistency, not category clarity.

Usage
-----
    # label1 and label2 are JSONL files with {"run_id": ..., "true_label": ...}
    python scripts/iaa_report.py data/gold/labeler1.jsonl data/gold/labeler2.jsonl

    # or compare auto-labels vs gold (to see where the classifier disagrees with humans)
    python scripts/iaa_report.py data/traces/real_cards.jsonl data/gold/demo_gold.jsonl \
        --field1 primary_category --field2 true_label

Output
------
Per-category agreement table, Cohen's kappa with bootstrap 95% CI,
and a confusion matrix for disagreements.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path


def _load(path: Path, field: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        run_id = rec.get("run_id", "")
        label = rec.get(field, "")
        if run_id and label:
            labels[run_id] = str(label).strip().upper()
    return labels


def _kappa(y1: list[str], y2: list[str]) -> float:
    n = len(y1)
    if n == 0:
        return float("nan")
    labels = sorted(set(y1) | set(y2))
    counts: dict[tuple[str, str], int] = Counter(zip(y1, y2, strict=True))
    p_agree = sum(counts.get((lbl, lbl), 0) for lbl in labels) / n
    counts1 = Counter(y1)
    counts2 = Counter(y2)
    p_expected = sum((counts1[lbl] / n) * (counts2[lbl] / n) for lbl in labels)
    if p_expected == 1.0:
        return 1.0
    return (p_agree - p_expected) / (1.0 - p_expected)


def _bootstrap_ci(y1: list[str], y2: list[str], n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(y1)
    kappas = []
    for _ in range(n_boot):
        indices = [rng.randint(0, n - 1) for _ in range(n)]
        b1 = [y1[i] for i in indices]
        b2 = [y2[i] for i in indices]
        kappas.append(_kappa(b1, b2))
    kappas.sort()
    lo = kappas[int(0.025 * n_boot)]
    hi = kappas[int(0.975 * n_boot)]
    return lo, hi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file1", help="First labeler JSONL file")
    parser.add_argument("file2", help="Second labeler JSONL file")
    parser.add_argument("--field1", default="true_label", help="Label field in file1 (default: true_label)")
    parser.add_argument("--field2", default="true_label", help="Label field in file2 (default: true_label)")
    parser.add_argument("--min-overlap", type=int, default=5, help="Minimum shared runs required (default: 5)")
    args = parser.parse_args()

    labels1 = _load(Path(args.file1), args.field1)
    labels2 = _load(Path(args.file2), args.field2)

    shared = sorted(set(labels1) & set(labels2))
    if len(shared) < args.min_overlap:
        print(f"Only {len(shared)} shared run IDs found (need >= {args.min_overlap}).")
        print(f"File 1 has {len(labels1)} labels, File 2 has {len(labels2)} labels.")
        print("Create an overlap by having both labelers rate the same runs.")
        return

    y1 = [labels1[r] for r in shared]
    y2 = [labels2[r] for r in shared]

    k = _kappa(y1, y2)
    lo, hi = _bootstrap_ci(y1, y2)

    n_agree = sum(a == b for a, b in zip(y1, y2, strict=True))
    pct_agree = n_agree / len(shared) * 100

    print("\nInter-annotator agreement report")
    print("=================================")

    print(f"Shared runs:      {len(shared)}")
    print(f"Raw agreement:    {n_agree}/{len(shared)} ({pct_agree:.1f}%)")
    print(f"Cohen's kappa:    {k:.3f}  [95% CI: {lo:.3f}, {hi:.3f}]")
    print()

    # interpretation
    if k >= 0.80:
        interp = "Strong agreement — categories are unambiguous."
    elif k >= 0.60:
        interp = "Moderate agreement — some categories need sharper definitions."
    elif k >= 0.40:
        interp = "Fair agreement — significant labeling ambiguity; refine guidelines."
    else:
        interp = "Poor agreement — categories are not reliably distinguishable."
    print(f"Interpretation:   {interp}")

    # disagreements
    disagreements = [(shared[i], y1[i], y2[i]) for i in range(len(shared)) if y1[i] != y2[i]]
    if disagreements:
        print(f"\nDisagreements ({len(disagreements)}):")
        print(f"  {'Run ID':<35} {'Labeler 1':<25} {'Labeler 2':<25}")
        print(f"  {'-'*35} {'-'*25} {'-'*25}")
        for run_id, l1, l2 in sorted(disagreements):
            print(f"  {run_id:<35} {l1:<25} {l2:<25}")

        # confusion pairs
        pair_counts: Counter = Counter((a, b) for _, a, b in disagreements)
        print("\nMost common disagreement pairs:")
        for (a, b), n in pair_counts.most_common(5):
            print(f"  {a} vs {b}: {n} case(s)")
        print("\nFocus annotation guideline work on these pairs to improve kappa.")
    else:
        print("\nNo disagreements — perfect agreement on the overlap set.")

    print("\nNote: kappa >= 0.80 is required before reporting accuracy as reliable.")
    print("With kappa < 0.80, the gold set labels are themselves ambiguous.\n")


if __name__ == "__main__":
    main()
