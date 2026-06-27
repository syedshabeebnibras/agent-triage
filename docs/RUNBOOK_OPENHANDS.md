# Runbook: generating real OpenHands traces

This is the honest core of the project. The fixtures in `data/traces/demo_runs.jsonl`
are hand-authored to be realistic, but **real evaluation numbers must come from
real agent runs.** This runbook walks through generating them.

You run this on a machine with Docker and an LLM API key (OpenHands runs each task
in a Docker sandbox). Budget a few dollars of inference for a small batch.

---

## 0. Prerequisites

- Docker installed and running
- Python 3.11+
- An LLM API key (Anthropic or OpenAI). Anthropic Claude is recommended to mirror
  a production coding-agent setup.
- ~$3–10 of API budget for a 20–50 task batch (depends on model + task difficulty)

## 1. Install OpenHands

```bash
pip install openhands-ai
# or follow https://github.com/All-Hands-AI/OpenHands for the latest install path
export ANTHROPIC_API_KEY=sk-ant-...
```

## 2. Pick a SWE-bench subset

Start small and cheap with **SWE-bench Lite** (300 tasks) — you only need a
subset. The goal is to collect a batch with a healthy mix of **failures** (those
are what we triage).

```bash
# OpenHands ships a SWE-bench evaluation harness. The exact command varies by
# version; the canonical entrypoint is its evaluation script:
#   evaluation/benchmarks/swe_bench/run_infer.sh
#
# Example (check the OpenHands docs for your version's flags):
./evaluation/benchmarks/swe_bench/run_infer.sh \
  llm.claude \
  HEAD \
  CodeActAgent \
  30 \                 # number of instances
  30 \                 # eval limit
  1 \                  # num workers
  princeton-nlp/SWE-bench_Lite \
  test
```

This produces an `output.jsonl` where each line is one instance's run, including
the trajectory (`history`), the produced `git_patch`, and (after the eval step)
whether it `resolved` the task.

## 3. Run the SWE-bench evaluation to get ground truth

OpenHands' eval step applies each predicted patch and runs the task's tests,
producing a report that marks each instance `resolved: true/false`. This is your
**ground-truth resolution** — the signal that tells us which runs *failed* (the
ones to triage) and lets the eval harness measure classification accuracy.

## 4. Normalize the output into AgentRun JSONL

Use the adapter to convert OpenHands output into our normalized schema:

```python
# scripts/ingest_openhands.py  (template — adjust paths to your output)
import json
from pathlib import Path
from agent_triage.harness.openhands_adapter import from_openhands
from agent_triage.schema.trace import TaskSpec, TestResult

src = Path("output.jsonl")          # OpenHands run output
out = Path("data/traces/real_runs.jsonl")

with src.open() as f, out.open("w") as w:
    for line in f:
        rec = json.loads(line)
        inst = rec.get("instance", {})
        task = TaskSpec(
            task_id=rec.get("instance_id", inst.get("instance_id", "unknown")),
            source="swe-bench",
            repo=inst.get("repo"),
            base_commit=inst.get("base_commit"),
            problem_statement=inst.get("problem_statement", ""),
        )
        resolved = rec.get("resolved", rec.get("test_result", {}).get("resolved"))
        run = from_openhands(
            rec,
            run_id=f"openhands-{task.task_id}",
            task=task,
            resolved=resolved,
            test_result=TestResult(passed=bool(resolved)) if resolved is not None else None,
        )
        # we only triage failures
        if run.failed:
            w.write(run.model_dump_json() + "\n")

print("wrote failed runs to", out)
```

```bash
python scripts/ingest_openhands.py
```

## 5. Triage the real failures

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # enables real LLM classification
triage batch data/traces/real_runs.jsonl --out data/traces/real_cards.jsonl
triage calibrate data/traces/real_runs.jsonl   # distribution + OTHER rate
```

## 6. Hand-label a gold set (this is what makes it credible)

Pick ~30–50 failed runs and label each with its true category. Open each run,
read the trajectory, and assign the category you believe is correct. Write them to
`data/gold/real_gold.jsonl`, one JSON object per line:

```json
{"run_id": "openhands-django__django-12345", "task_id": "django__django-12345", "true_category": "CONTEXT_RETRIEVAL", "labeler": "you", "notes": "edited wrong module"}
```

Labeling tips (keep categories distinguishable):
- **CONTEXT_RETRIEVAL** vs **REASONING**: did it find the right file? If it never
  opened the file with the bug → retrieval. If it edited the right file but the
  logic is wrong → reasoning.
- **TOOL_USE** vs **REASONING**: was the *plan* fine but the *action* broken
  (patch won't apply, repeated identical command)? → tool use.
- **VERIFICATION**: did it finish without running tests, or finish on red? That's
  verification regardless of whether the underlying fix was close.
- **INFRA_ERROR** vs **ENVIRONMENT**: rate limits / 5xx / sandbox crash → infra.
  Missing deps / wrong runtime / build failure → environment.

For a stronger gold set, have a second person label a subset and compute
inter-annotator agreement — then you can report that your *humans* agree at kappa
X, which bounds how well any classifier can do.

## 7. Evaluate

```bash
triage eval data/traces/real_runs.jsonl data/gold/real_gold.jsonl
```

This prints overall accuracy, Cohen's kappa (with bootstrap CI), and per-class
precision/recall/F1, and writes a full report to `eval_report.json`.

## 8. Validate / revise the taxonomy

Look at the calibration output and the confusion matrix:
- **High `OTHER` rate** (say >15%) → the taxonomy is missing a category. Read the
  OTHER runs; if a pattern recurs, add a category to `taxonomy/categories.py`,
  bump `TAXONOMY_VERSION`, and re-label.
- **Two categories that constantly get confused** → their definitions overlap;
  tighten them or merge.

Record what you changed and why. **This is the sentence that makes the project
honest:** "I defined the taxonomy a priori, ran N real OpenHands failures through
it, found the OTHER rate was X% and that A/B were confused, and revised to vY —
here's the before/after."

## 9. Refresh the dashboard demo data (optional)

To show real triaged runs on the deployed dashboard, export the real cards into
the dashboard's demo data file (or point `NEXT_PUBLIC_API_BASE` at the live API
so the dashboard pulls live verdicts).

---

## What "done" looks like

- `data/traces/real_runs.jsonl` — real OpenHands failures, normalized
- `data/gold/real_gold.jsonl` — your hand labels
- `eval_report.json` — measured accuracy + kappa + per-class F1 on real data
- a short note in `docs/EVAL_NOTES.md` recording the taxonomy validation story
