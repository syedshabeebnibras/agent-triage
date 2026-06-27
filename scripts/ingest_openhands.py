"""Convert raw OpenHands SWE-bench output.jsonl into normalized AgentRun JSONL.

Usage:
    python scripts/ingest_openhands.py                       # defaults
    python scripts/ingest_openhands.py --src path/to/output.jsonl --out data/traces/real_runs.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_triage.harness.openhands_adapter import from_openhands
from agent_triage.schema.trace import TaskSpec, TestResult


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="data/openhands_output/output.jsonl", help="Raw OpenHands JSONL path")
    p.add_argument("--out", default="data/traces/real_runs.jsonl", help="Output path for normalized AgentRun JSONL")
    p.add_argument("--all", dest="all_runs", action="store_true", help="Include resolved runs, not just failures")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.src)
    out = Path(args.out)

    if not src.exists():
        raise SystemExit(f"Source file not found: {src}\nRun scripts/run_swebench_smoke.sh first.")

    out.parent.mkdir(parents=True, exist_ok=True)

    total = written = skipped_resolved = 0

    with src.open() as f_in, out.open("w") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            total += 1
            rec = json.loads(line)

            inst = rec.get("instance") or {}
            instance_id = rec.get("instance_id") or inst.get("instance_id", f"unknown-{total}")

            task = TaskSpec(
                task_id=instance_id,
                source="swe-bench",
                repo=inst.get("repo"),
                base_commit=inst.get("base_commit"),
                problem_statement=inst.get("problem_statement", ""),
            )

            test_block = rec.get("test_result") or {}
            resolved = rec.get("resolved")
            if resolved is None:
                resolved = test_block.get("resolved")

            test_result = TestResult(passed=bool(resolved)) if resolved is not None else None

            run = from_openhands(
                rec,
                run_id=f"openhands-{instance_id}",
                task=task,
                resolved=resolved,
                test_result=test_result,
                final_patch=rec.get("git_patch") or test_block.get("git_patch"),
            )

            if not args.all_runs and not run.failed:
                skipped_resolved += 1
                continue

            f_out.write(run.model_dump_json() + "\n")
            written += 1

    print(f"Processed {total} records → wrote {written} runs to {out}")
    if skipped_resolved:
        print(f"  (skipped {skipped_resolved} resolved/passing runs — use --all to include them)")


if __name__ == "__main__":
    main()
