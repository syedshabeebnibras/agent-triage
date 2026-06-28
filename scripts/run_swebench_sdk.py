"""Run SWE-bench Lite instances via the OpenHands SDK (LocalConversation).

This collects failure trajectories at MAX_TURNS=100 (vs the original 20).
It does NOT require Docker or the full OpenHands runtime — it uses the
installed `openhands-ai` SDK with a local workspace.

Usage
-----
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/run_swebench_sdk.py                     # 60 instances
    python scripts/run_swebench_sdk.py --max-instances 10  # quick pilot
    python scripts/run_swebench_sdk.py --repo django --max-instances 20

Output
------
    data/traces/run_<timestamp>/
        <instance_id>.jsonl   — events in AgentRun format (one per instance)
        metadata.json         — run config for reproducibility
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

OPENHANDS_SUPPRESS_BANNER = "1"
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")


def _check_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise SystemExit("ERROR: Set ANTHROPIC_API_KEY or OPENAI_API_KEY before running.")
    return key


def _load_instances(repo_filter: str, max_instances: int) -> list[dict]:
    from datasets import load_dataset  # type: ignore[import-untyped]

    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    instances = [
        {
            "instance_id": r["instance_id"],
            "repo": r["repo"],
            "problem_statement": r["problem_statement"],
            "base_commit": r.get("base_commit", ""),
        }
        for r in ds
        if not repo_filter or repo_filter in r["repo"]
    ][:max_instances]
    return instances


def _run_instance(
    instance: dict,
    model: str,
    api_key: str,
    max_turns: int,
    output_file: Path,
) -> bool:
    """Run one SWE-bench instance and write events to output_file as JSONL."""
    from openhands.sdk import LLM, Agent, LocalConversation, LocalWorkspace
    from openhands.sdk.event.base import Event

    llm = LLM(
        model=model,
        api_key=api_key,
        timeout=180,
        num_retries=3,
    )
    agent = Agent(llm=llm)

    events: list[dict] = []

    def capture(event: Event) -> None:
        try:
            events.append(event.model_dump(mode="json"))
        except Exception:
            events.append({"type": type(event).__name__, "raw": str(event)})

    with tempfile.TemporaryDirectory() as workspace_dir:
        try:
            workspace = LocalWorkspace(workspace_dir)
            conv = LocalConversation(
                agent=agent,
                workspace=workspace,
                max_iteration_per_run=max_turns,
                callbacks=[capture],
                delete_on_close=True,
            )
            # send_message() enqueues the task; run() executes until finish or cap
            conv.send_message(instance["problem_statement"])
            conv.run()
        except Exception as exc:
            events.append({
                "type": "error",
                "message": str(exc),
                "instance_id": instance["instance_id"],
            })

    # Write to output: a pseudo-AgentRun JSONL with the raw events
    record = {
        "run_id": f"sdk-{instance['instance_id']}",
        "agent": "openhands-sdk",
        "model": model,
        "instance_id": instance["instance_id"],
        "repo": instance["repo"],
        "problem_statement": instance["problem_statement"],
        "events": events,
        "event_count": len(events),
        "resolved": False,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    output_file.write_text(json.dumps(record) + "\n")
    return True


def main(args: argparse.Namespace) -> None:
    api_key = _check_api_key()
    model = args.model
    max_turns = args.max_turns
    max_instances = args.max_instances

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir or f"data/traces/run_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Agent Triage: SWE-bench SDK runner ===")
    print(f"Model:      {model}")
    print(f"Max turns:  {max_turns}  (was 20 in original run — key change)")
    print(f"Instances:  up to {max_instances}")
    print(f"Filter:     {args.repo or 'none'}")
    print(f"Output:     {output_dir}")
    print()

    (output_dir / "metadata.json").write_text(json.dumps({
        "model": model,
        "max_turns": max_turns,
        "max_instances": max_instances,
        "repo_filter": args.repo or "",
        "runner": "openhands-sdk",
        "started_at": datetime.now(UTC).isoformat(),
    }, indent=2))

    print("Loading SWE-bench Lite instances...")
    instances = _load_instances(args.repo or "", max_instances)
    print(f"Loaded {len(instances)} instances\n")

    succeeded = 0
    failed = 0

    for i, inst in enumerate(instances, 1):
        iid = inst["instance_id"]
        out_file = output_dir / f"{iid}.jsonl"

        if out_file.exists():
            print(f"[{i}/{len(instances)}] {iid} — already done, skipping")
            succeeded += 1
            continue

        print(f"[{i}/{len(instances)}] {iid} ...", end=" ", flush=True)
        t0 = time.monotonic()
        try:
            _run_instance(inst, model, api_key, max_turns, out_file)
            elapsed = round(time.monotonic() - t0, 1)
            print(f"done ({elapsed}s)")
            succeeded += 1
        except Exception as exc:
            elapsed = round(time.monotonic() - t0, 1)
            print(f"FAILED ({elapsed}s): {exc}")
            failed += 1

    print(f"\n=== Run complete: {len(instances)} instances ({succeeded} ok, {failed} failed) ===")
    print(f"Output: {output_dir}\n")
    print("Next steps:")
    print("  1. Convert to AgentRun format for triage:")
    print("     python3 -c \"")
    print("       from agent_triage.harness.openhands_adapter import load_openhands_file")
    print(f"       runs = load_openhands_file('{output_dir}/')\"")
    print("  2. Run triage batch:")
    print(f"     triage batch {output_dir}/*.jsonl --output data/traces/new_cards.jsonl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="", help="Filter to instances from this repo")
    parser.add_argument("--max-instances", type=int, default=60, help="Max instances to run (default: 60)")
    parser.add_argument("--max-turns", type=int, default=100, help="Max agent turns per instance (default: 100)")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001", help="Model name")
    parser.add_argument("--output-dir", default="", help="Output directory (default: data/traces/run_<timestamp>)")
    args = parser.parse_args()
    main(args)
