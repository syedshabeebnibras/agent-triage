#!/usr/bin/env bash
# Run a SWE-bench Lite subset with OpenHands at full turn budgets (MAX_TURNS=100).
#
# This script addresses the core data limitation: the original 40 runs used
# MAX_TURNS=20, which inflated IMPLEMENTATION_STALL because agents hit the cap
# before ever calling edit_file. At 100 turns, agents that were stalling will
# either edit or reveal a deeper failure mode (REASONING, CONTEXT_RETRIEVAL).
#
# Prerequisites
# -------------
#   export ANTHROPIC_API_KEY=sk-ant-...
#   pip install openhands-ai   # or use the Docker image
#   git clone https://github.com/princeton-nlp/SWE-bench
#
# Usage
# -----
#   bash scripts/run_swebench_batch.sh                    # run all instances
#   bash scripts/run_swebench_batch.sh django 20          # 20 django instances
#   bash scripts/run_swebench_batch.sh "" 10 gpt-4o       # 10 instances with GPT-4o
#
# Outputs
# -------
#   data/traces/run_<timestamp>/     — one trajectory JSONL per instance
#   data/traces/run_<timestamp>/metadata.json  — run config for reproducibility

set -euo pipefail

REPO_FILTER="${1:-}"          # optional: filter to a specific repo (e.g. "django")
MAX_INSTANCES="${2:-60}"      # how many instances to run
MODEL="${3:-claude-haiku-4-5-20251001}"  # which model to use
MAX_TURNS=100                 # full budget — key change from the original 20
SWEBENCH_SPLIT="lite"         # "lite" or "full"
OUTPUT_DIR="data/traces/run_$(date +%Y%m%d_%H%M%S)"

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: Set ANTHROPIC_API_KEY or OPENAI_API_KEY before running."
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "=== Agent Triage: SWE-bench batch runner ==="
echo "Model:      $MODEL"
echo "Max turns:  $MAX_TURNS  (was 20 in original run — this is the key change)"
echo "Instances:  up to $MAX_INSTANCES"
echo "Filter:     ${REPO_FILTER:-none}"
echo "Output:     $OUTPUT_DIR"
echo ""

# Write run metadata for reproducibility
cat > "$OUTPUT_DIR/metadata.json" <<METADATA
{
  "model": "$MODEL",
  "max_turns": $MAX_TURNS,
  "max_instances": $MAX_INSTANCES,
  "repo_filter": "$REPO_FILTER",
  "swebench_split": "$SWEBENCH_SPLIT",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
METADATA

# Fetch the SWE-bench instance list
INSTANCES_FILE=$(mktemp)
python3 - <<PYEOF > "$INSTANCES_FILE"
import json
from datasets import load_dataset

ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
instances = [
    {"instance_id": r["instance_id"], "repo": r["repo"], "problem_statement": r["problem_statement"]}
    for r in ds
    if not "${REPO_FILTER}" or "${REPO_FILTER}" in r["repo"]
][:${MAX_INSTANCES}]
print(json.dumps(instances))
PYEOF

INSTANCE_COUNT=$(python3 -c "import json,sys; print(len(json.load(sys.stdin)))" < "$INSTANCES_FILE")
echo "Loaded $INSTANCE_COUNT instances from SWE-bench $SWEBENCH_SPLIT"

# Run each instance
COUNT=0
while IFS= read -r INSTANCE; do
    INSTANCE_ID=$(echo "$INSTANCE" | python3 -c "import json,sys; print(json.load(sys.stdin)['instance_id'])")
    OUT_FILE="$OUTPUT_DIR/${INSTANCE_ID}.jsonl"

    echo "[$((COUNT+1))/$INSTANCE_COUNT] $INSTANCE_ID"

    # Run OpenHands on this instance
    # The --json flag writes a structured output we can normalize with the adapter
    python3 -m openhands.core.main \
        --model "$MODEL" \
        --max-iterations "$MAX_TURNS" \
        --task "$(echo "$INSTANCE" | python3 -c "import json,sys; print(json.load(sys.stdin)['problem_statement'])")" \
        --swe-bench-instance-id "$INSTANCE_ID" \
        --output-file "$OUT_FILE" \
        2>&1 | tail -3 || echo "  WARNING: instance $INSTANCE_ID failed (check $OUT_FILE)"

    COUNT=$((COUNT + 1))
done < <(python3 -c "import json,sys; [print(json.dumps(i)) for i in json.load(sys.stdin)]" < "$INSTANCES_FILE")

echo ""
echo "=== Run complete: $COUNT instances ==="
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "  1. Normalize with the OpenHands adapter:"
echo "     python3 -c \""
echo "       from agent_triage.harness.openhands_adapter import load_openhands_file"
echo "       import json"
echo "       runs = load_openhands_file('$OUTPUT_DIR/')"
echo "       print(f'{len(runs)} runs loaded')\""
echo "  2. Run triage over the batch:"
echo "     triage batch $OUTPUT_DIR/*.jsonl --output data/traces/new_cards.jsonl"
echo "  3. Hand-label a gold set from the new batch:"
echo "     cp data/traces/new_cards.jsonl data/gold/labeler1_new.jsonl"
echo "     # edit true_label fields manually"
echo "  4. Measure IAA if a second labeler is available:"
echo "     python scripts/iaa_report.py data/gold/labeler1_new.jsonl data/gold/labeler2_new.jsonl"
