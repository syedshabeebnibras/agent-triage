"""Interactive terminal script to hand-label triage cards for a gold set.

Usage:
    python scripts/label_gold.py data/traces/bash_cards.jsonl data/gold/sdk_bash_gold.jsonl
    python scripts/label_gold.py data/traces/bash_cards.jsonl data/gold/sdk_bash_gold.jsonl --n 10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

VALID = {
    "SCOPING", "ENVIRONMENT", "CONTEXT_RETRIEVAL", "REASONING",
    "VERIFICATION", "TOOL_USE", "RESOURCE_LIMIT", "IMPLEMENTATION_STALL",
    "INFRA_ERROR", "OTHER",
}
SHORTCUTS = {
    "sc": "SCOPING", "en": "ENVIRONMENT", "cr": "CONTEXT_RETRIEVAL",
    "re": "REASONING", "ve": "VERIFICATION", "tu": "TOOL_USE",
    "rl": "RESOURCE_LIMIT", "is": "IMPLEMENTATION_STALL",
    "ie": "INFRA_ERROR", "ot": "OTHER",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cards_path", help="JSONL of TriageCards to label")
    parser.add_argument("gold_path", help="Output JSONL for GoldLabels")
    parser.add_argument("--n", type=int, default=10, help="Number of cards to label")
    parser.add_argument("--labeler", default="human", help="Your name")
    args = parser.parse_args()

    cards = [json.loads(l) for l in Path(args.cards_path).read_text().splitlines() if l.strip()]
    gold_path = Path(args.gold_path)
    gold_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip already-labeled
    labeled_ids: set[str] = set()
    if gold_path.exists():
        for line in gold_path.read_text().splitlines():
            if line.strip():
                labeled_ids.add(json.loads(line)["run_id"])

    to_label = [c for c in cards if c["run_id"] not in labeled_ids][: args.n]
    print(f"\nLabeling {len(to_label)} cards (press Ctrl-C to stop and save progress)\n")
    print("Shortcuts: sc=SCOPING en=ENVIRONMENT cr=CONTEXT_RETRIEVAL re=REASONING")
    print("           ve=VERIFICATION tu=TOOL_USE rl=RESOURCE_LIMIT is=IMPLEMENTATION_STALL")
    print("           ie=INFRA_ERROR ot=OTHER  |  'a' to agree with classifier\n")

    with open(gold_path, "a") as out:
        for i, card in enumerate(to_label, 1):
            print(f"─── [{i}/{len(to_label)}] {card['run_id']} ───")
            print(f"Classifier said: {card['primary_category']} ({card['confidence']:.0%})")
            print(f"Root cause: {card['root_cause'][:200]}")
            for ev in card["evidence"][:2]:
                if ev.get("excerpt"):
                    print(f"  Evidence[{ev['step_index']}]: {ev['excerpt'][:120]}")
            print()

            while True:
                raw = input("Your label (or 'a' to agree, 's' to skip): ").strip().lower()
                if raw == "s":
                    print("Skipped.\n")
                    break
                if raw == "a":
                    true_cat = card["primary_category"]
                elif raw in SHORTCUTS:
                    true_cat = SHORTCUTS[raw]
                elif raw.upper() in VALID:
                    true_cat = raw.upper()
                else:
                    print(f"  Unknown — valid: {', '.join(sorted(VALID))}")
                    continue
                notes = input("Notes (optional, Enter to skip): ").strip()
                label = {
                    "run_id": card["run_id"],
                    "task_id": card["task_id"],
                    "true_category": true_cat,
                    "labeler": args.labeler,
                    "notes": notes,
                }
                out.write(json.dumps(label) + "\n")
                out.flush()
                print(f"  Saved: {true_cat}\n")
                break

    total = sum(1 for _ in gold_path.read_text().splitlines() if _.strip())
    print(f"\nDone. {total} labels in {gold_path}")


if __name__ == "__main__":
    main()
