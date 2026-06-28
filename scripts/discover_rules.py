"""Automated rule discovery via decision tree on extracted signals.

Trains a decision tree on the gold-labeled cards + extracted signals to find
NEW deterministic rules the LLM currently handles. Every rule discovered here
is a candidate to move from the 7.5% LLM path to the 92.5% free rule path.

Usage
-----
    python scripts/discover_rules.py data/traces/real_cards.jsonl data/gold/demo_gold.jsonl
    python scripts/discover_rules.py --min-precision 0.90 --max-depth 4 ...

Requirements
------------
scikit-learn:  pip install scikit-learn

Output
------
Prints each discovered rule as a human-readable IF/THEN clause with precision
and support, ready to be translated into a new block in signals.rule_based_guess().
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _load_cards(path: Path) -> list[dict]:
    cards = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cards.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return cards


def _merge_with_gold(cards: list[dict], gold: list[dict]) -> list[dict]:
    """Replace auto-labels with gold labels where available."""
    gold_map = {g["run_id"]: g["true_label"] for g in gold if "true_label" in g}
    merged = []
    for c in cards:
        c = dict(c)
        if c.get("run_id") in gold_map:
            c["true_label"] = gold_map[c["run_id"]]
        else:
            c["true_label"] = c.get("primary_category", "OTHER")
        merged.append(c)
    return merged


def _extract_features(card: dict) -> dict:
    """Pull signal features from a card's stored metadata."""
    sig = card.get("signals") or {}
    return {
        "produced_patch": int(sig.get("produced_patch", False)),
        "no_file_edits": int(sig.get("no_file_edits", True)),
        "ran_tests": int(sig.get("ran_tests", False)),
        "tests_passed": int(sig.get("tests_passed") or 0),
        "finished_without_testing": int(sig.get("finished_without_testing", False)),
        "finished_on_red": int(sig.get("finished_on_red", False)),
        "hit_resource_limit": int(sig.get("hit_resource_limit", False)),
        "catastrophic_edit": int(sig.get("catastrophic_edit", False)),
        "verified_without_editing": int(sig.get("verified_without_editing", False)),
        "step_count": int(sig.get("step_count", 0)),
        "n_repeated_commands": len(sig.get("repeated_commands") or []),
        "n_error_fingerprints": len(sig.get("error_fingerprints") or []),
        "n_infra_fps": sum(1 for f in (sig.get("error_fingerprints") or []) if f.get("code") == "INFRA_ERROR"),
        "n_env_fps": sum(1 for f in (sig.get("error_fingerprints") or []) if f.get("code") == "ENVIRONMENT"),
        "n_tool_fps": sum(1 for f in (sig.get("error_fingerprints") or []) if f.get("code") == "TOOL_USE"),
        "unique_files_opened": int(sig.get("unique_files_opened", 0)),
        "assertion_after_edit": int(sig.get("assertion_after_edit", False)),
        "narrow_file_search": int(sig.get("narrow_file_search", False)),
    }


def _rule_from_tree(tree, feature_names: list[str], label_names: list[str], *, min_precision: float, min_support: int) -> list[str]:
    """Walk a fitted DecisionTree and extract high-precision leaf rules."""
    from sklearn.tree import _tree

    tree_ = tree.tree_
    rules = []

    def recurse(node: int, path: list[str]) -> None:
        if tree_.feature[node] == _tree.TREE_UNDEFINED:
            # leaf node
            counts = tree_.value[node][0]
            total = int(counts.sum())
            best_class = int(counts.argmax())
            precision = counts[best_class] / total if total > 0 else 0.0
            if precision >= min_precision and total >= min_support:
                label = label_names[best_class]
                rule = " AND ".join(path) if path else "(root)"
                rules.append((label, round(precision, 3), total, rule))
            return

        feat = feature_names[tree_.feature[node]]
        threshold = tree_.threshold[node]
        recurse(node * 2 + 1, path + [f"{feat} <= {threshold:.1f}"])
        recurse(node * 2 + 2, path + [f"{feat} > {threshold:.1f}"])

    recurse(0, [])
    return rules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards_file", help="Cards JSONL (with embedded signal data)")
    parser.add_argument("gold_file", nargs="?", help="Optional gold labels JSONL to override auto-labels")
    parser.add_argument("--min-precision", type=float, default=0.85, help="Min precision to report a rule (default: 0.85)")
    parser.add_argument("--min-support", type=int, default=3, help="Min examples in leaf to report a rule (default: 3)")
    parser.add_argument("--max-depth", type=int, default=5, help="Max tree depth (default: 5)")
    args = parser.parse_args()

    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        sys.exit("scikit-learn is required: pip install scikit-learn")

    cards = _load_cards(Path(args.cards_file))
    if args.gold_file:
        gold = _load_cards(Path(args.gold_file))
        cards = _merge_with_gold(cards, gold)

    if not cards:
        sys.exit("No cards loaded.")

    # filter cards that have signal data
    cards_with_signals = [c for c in cards if c.get("signals")]
    if not cards_with_signals:
        print(f"WARNING: None of the {len(cards)} cards have embedded signal data.")
        print("Re-run triage with --emit-signals to include signals in output.")
        print("Falling back to feature-engineered fields from card metadata.\n")
        cards_with_signals = cards  # try anyway with zeros

    X_raw = [_extract_features(c) for c in cards_with_signals]
    y = [c.get("true_label", c.get("primary_category", "OTHER")) for c in cards_with_signals]

    feature_names = list(X_raw[0].keys())
    X = [[row[f] for f in feature_names] for row in X_raw]

    label_names = sorted(set(y))
    y_enc = [label_names.index(label) for label in y]

    dist = Counter(y)
    print(f"Training on {len(cards_with_signals)} cards:")
    for label, n in dist.most_common():
        print(f"  {label}: {n}")
    print()

    clf = DecisionTreeClassifier(max_depth=args.max_depth, min_samples_leaf=args.min_support, random_state=42)
    clf.fit(X, y_enc)

    score = clf.score(X, y_enc)
    print(f"Tree training accuracy: {score:.1%} (depth={clf.get_depth()}, leaves={clf.get_n_leaves()})")
    print(f"\nHigh-precision rules (precision >= {args.min_precision}, support >= {args.min_support}):\n")

    rules = _rule_from_tree(clf, feature_names, label_names, min_precision=args.min_precision, min_support=args.min_support)

    if not rules:
        print("No rules found meeting the thresholds. Try --min-precision 0.75 or --min-support 2.")
        return

    rules.sort(key=lambda r: (-r[1], -r[2]))
    for label, precision, support, rule in rules:
        print(f"  IF {rule}")
        print(f"  THEN {label}  [precision={precision:.0%}, n={support}]")
        print()

    print("Translate high-precision rules into new blocks in engine/signals.py:rule_based_guess().")
    print("Rules with precision >= 0.90 and n >= 5 are strong candidates for the free rule path.")


if __name__ == "__main__":
    main()
